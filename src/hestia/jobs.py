"""Background tasks: detached agent runs with completion notifications.

Modeled on kimi-code: a tool can start long work in the background and return
a task id immediately; the agent keeps working or idles, and when the task
reaches a terminal state the originating session gets a notification message
and, if idle, a continuation turn reacts to the result.

Jobs run in dedicated worker threads, each with its own event loop, so a
blocking request thread can never starve them and a job can never block a
chat turn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from datetime import datetime, timezone

from sqlmodel import Session, select

from hestia import actions, notify, settings, totem_store, usage
from hestia.agent import loop as agent_loop
from hestia.agent.prompt import build_system_prompt
from hestia.agent.run import run_once
from hestia.providers.base import provider_client, resolve_api_key
from hestia.registry.db import engine
from hestia.registry.models import (
    AgentConfig,
    BackgroundTask,
    Message,
    Project,
    Provider,
    Session as ChatSession,
)
from hestia.tools import build_registry
from hestia.tools.registry import ProjectContext

logger = logging.getLogger("hestia.jobs")

MAX_WORKERS = max(1, int(os.environ.get("HESTIA_BACKGROUND_MAX", "3")))
TIMEOUT = max(60, int(os.environ.get("HESTIA_BACKGROUND_TIMEOUT", "1800")))

BACKGROUND_NOTE = """\
## Background tasks
Long jobs can run in the background: call start_background_task (or
run_subagent with run_in_background=true) with a short description. It returns
a task id immediately; keep working or stop and the owner will be notified.
Use job_list and job_output to check progress, and job_stop to cancel. Do not
poll in a loop: you will be woken with the result when it finishes."""

ACTIVE_SESSIONS: set[str] = set()
_active_lock = threading.Lock()


def mark_active(session_id: str) -> None:
    with _active_lock:
        ACTIVE_SESSIONS.add(session_id)


def mark_idle(session_id: str) -> None:
    with _active_lock:
        ACTIVE_SESSIONS.discard(session_id)


def is_active(session_id: str) -> bool:
    with _active_lock:
        return session_id in ACTIVE_SESSIONS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent_for(db: Session, key: str) -> AgentConfig | None:
    key = (key or "chat").strip()
    agent = actions.resolve_action(db, key)
    if agent is None:
        agent = db.exec(select(AgentConfig).where(AgentConfig.name == key)).first()
    return agent


def _provider_for(db: Session, project: Project, agent: AgentConfig | None) -> Provider | None:
    provider_id = (agent.provider_id if agent else None) or project.default_provider_id
    provider = db.get(Provider, provider_id) if provider_id else None
    return actions.effective_provider(agent, provider)


def as_dict(job: BackgroundTask) -> dict:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "session_id": job.session_id,
        "kind": job.kind,
        "description": job.description,
        "instruction": job.instruction,
        "action": job.action,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def submit(
    *,
    project_id: int,
    session_id: str | None,
    kind: str,
    instruction: str,
    description: str,
    action: str = "chat",
    payload: str = "{}",
) -> int:
    with Session(engine()) as db:
        job = BackgroundTask(
            project_id=project_id,
            session_id=session_id,
            kind=kind,
            instruction=instruction,
            description=description or instruction[:80],
            action=action or "chat",
            payload=payload,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    manager.enqueue(job_id)
    return job_id


def stop(job_id: int) -> dict | None:
    with Session(engine()) as db:
        job = db.get(BackgroundTask, job_id)
        if job is None:
            return None
        if job.status in ("queued", "running"):
            job.status = "stopped"
            job.finished_at = _now()
            if not job.result:
                job.result = "stopped by request"
            db.add(job)
            db.commit()
            db.refresh(job)
        return as_dict(job)


class JobManager:
    """Thread-based worker pool. Jobs each get their own asyncio loop."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._started = threading.Event()

    def start(self) -> None:
        if self._started.is_set():
            return
        self._started.set()
        _reconcile()
        for i in range(MAX_WORKERS):
            worker = threading.Thread(target=self._worker, name=f"hestia-job-{i}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def enqueue(self, job_id: int) -> None:
        self.start()
        self._queue.put(job_id)

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                asyncio.run(self._run(job_id))
            except Exception:
                logger.exception("background job %s crashed", job_id)
            finally:
                self._queue.task_done()

    async def _run(self, job_id: int) -> None:
        with Session(engine()) as db:
            job = db.get(BackgroundTask, job_id)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = _now()
            db.add(job)
            db.commit()
            project = db.get(Project, job.project_id)
            if project is None:
                job.status = "error"
                job.error = "project deleted"
                job.finished_at = _now()
                db.add(job)
                db.commit()
                return
            timed_out = False
            try:
                report, error, tokens = await asyncio.wait_for(
                    _execute_job(db, job, project), timeout=TIMEOUT
                )
            except asyncio.TimeoutError:
                report, error, timed_out = "", f"timed out after {TIMEOUT}s", True
            except Exception as e:  # noqa: BLE001
                report, error = "", f"{type(e).__name__}: {e}"
            db.refresh(job)
            if job.status != "stopped":  # a stop request wins over the result
                job.status = "timed_out" if timed_out else ("failed" if error else "completed")
            job.result = (report or "").strip()[:20000]
            job.error = (error or "")[:2000]
            job.finished_at = _now()
            db.add(job)
            db.commit()
        await _deliver(job_id)


async def _execute_swarm(
    db: Session, job: BackgroundTask, project: Project
) -> tuple[str, str | None, dict]:
    from hestia.tools.subagents import run_swarm

    try:
        data = json.loads(job.payload or "{}")
    except ValueError:
        data = {}
    tasks = data.get("tasks") or []
    if not tasks:
        return "", "swarm job has no tasks", {}
    ctx = ProjectContext.from_project(project)
    ctx.session_id = job.session_id
    results = await asyncio.to_thread(
        run_swarm,
        ctx,
        db,
        str(data.get("directive") or ""),
        tasks,
        int(data.get("max_parallel") or 3),
        data.get("write_scope") or None,
    )
    lines = []
    failed = False
    for r in results:
        ok = r.get("status") != "error"
        failed = failed or not ok
        lines.append(f"- [{'ok' if ok else 'error'}] {r.get('agent', '?')}: "
                     f"{(r.get('summary') or r.get('error') or '').strip()[:400]}")
    # Include the structured roster so the UI can rebuild the swarm card.
    lines.append("")
    lines.append("<agent_swarm_result>" + json.dumps(results) + "</agent_swarm_result>")
    return "\n".join(lines), ("some swarm tasks failed" if failed else None), {}


async def _execute_job(
    db: Session, job: BackgroundTask, project: Project
) -> tuple[str, str | None, dict]:
    from hestia.tools.subagents import SUBAGENT_PROMPT, subagent_system

    if job.kind == "swarm":
        return await _execute_swarm(db, job, project)

    agent = _agent_for(db, job.action or "chat")
    provider = _provider_for(db, project, agent)
    if provider is None:
        return "", "no provider configured for this project", {}
    ctx = ProjectContext.from_project(project)
    ctx.session_id = job.session_id
    instruction = job.instruction or job.description or "Do the background task."
    try:
        job_payload = json.loads(job.payload or "{}")
    except ValueError:
        job_payload = {}
    write_scope = job_payload.get("write_scope") or None

    mode = None
    if job.kind == "subagent":
        if agent:
            system = subagent_system(agent)
            groups = agent.tools
            mode = agent.mode or "read"
        else:
            system = SUBAGENT_PROMPT
            groups = "repo,files"
            mode = "read"
    else:
        digest = totem_store.digest(ctx.memory_path, task=instruction)
        system = build_system_prompt(
            ctx,
            agents_md=project.agents_md,
            memory_context=digest.get("context", ""),
            user_task=instruction,
            extra_context=settings.prompt_context(db),
        )
        if agent and agent.system_prompt:
            system += f"\n\n## Agent instructions\n{agent.system_prompt}"
        system += "\n\n" + BACKGROUND_NOTE
        groups = (
            actions.ACTIONS_BY_KEY.get(job.action or "chat", {}).get("tools")
            or "repo,files,github,memory,workspace,tasks,agents"
        )

    report, error, tokens = await run_once(
        project,
        provider,
        system,
        instruction,
        groups=groups,
        max_turns=None,
        tasks_db=db,
        writes=bool(project.allow_git_writes),
        mode=mode,
        write_allowlist=tuple(write_scope) if write_scope else None,
    )
    usage.record(
        db,
        project.id,
        session_id=job.session_id,
        action=f"background:{job.kind}",
        model=provider.model,
        usage=tokens,
    )
    return report, error, tokens


def _wall_time(job: BackgroundTask) -> str:
    if not job.started_at or not job.finished_at:
        return ""
    seconds = max(0, int((job.finished_at - job.started_at).total_seconds()))
    if seconds < 60:
        return f"Wall time: {seconds}s"
    return f"Wall time: {seconds // 60}m {seconds % 60}s"


def _notification_text(job: BackgroundTask, summary: str) -> str:
    label = job.description or job.instruction or job.kind
    severity = "info" if job.status == "completed" else "warning"
    line = f"{label} {job.status}."
    if job.error:
        line = f"{label} {job.status}: {job.error}"
    body = "\n".join(x for x in [_wall_time(job), line, "", summary] if x != "")
    return (
        f'<notification category="task" type="task.{job.status}" '
        f'source_kind="background_task" source_id="{job.id}">\n'
        f"Title: Background {job.kind} {job.status}\n"
        f"Severity: {severity}\n"
        f"{body}\n"
        "</notification>"
    )


async def _deliver(job_id: int) -> None:
    with Session(engine()) as db:
        job = db.get(BackgroundTask, job_id)
        if job is None or job.notified:
            return
        project = db.get(Project, job.project_id)
        project_id = job.project_id
        project_name = project.name if project else ""
        session_id = job.session_id
        status = job.status
        summary = (job.error or job.result or "(no result)").strip()
        auto_continue = settings.get_bool(db, "background_auto_continue", True)
        if session_id is not None and db.get(ChatSession, session_id) is not None:
            db.add(
                Message(
                    session_id=session_id,
                    role="notification",
                    content=_notification_text(job, summary[:4000]),
                )
            )
        job.notified = True
        db.add(job)
        db.commit()

    ok = status == "completed"
    notify.send(
        f"Background task {status}: {project_name or 'project'}",
        summary[:600],
        "default" if ok else "high",
        ["white_check_mark"] if ok else ["warning"],
        settings.notification_url(f"/p/{project_id}/background"),
    )

    if (
        session_id is not None
        and auto_continue
        and not is_active(session_id)
    ):
        await _continue(session_id, project_id)


def _replay(db: Session, session_id: str, system: str) -> list[dict]:
    rows = db.exec(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    ).all()
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in rows:
        if m.role == "assistant" and m.tool_calls:
            try:
                calls = json.loads(m.tool_calls)
            except ValueError:
                calls = []
            messages.append({"role": "assistant", "content": m.content, "tool_calls": calls})
        elif m.role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                    "content": m.content,
                }
            )
        elif m.role == "notification":
            messages.append({"role": "user", "content": f"[background task]\n{m.content}"})
        else:
            messages.append({"role": m.role, "content": m.content})
    return messages


async def _continue(session_id: str, project_id: int) -> None:
    if is_active(session_id):
        return
    mark_active(session_id)
    try:
        with Session(engine()) as db:
            project = db.get(Project, project_id)
            session = db.get(ChatSession, session_id)
            if project is None or session is None:
                return
            agent = _agent_for(db, session.action or "chat")
            provider = _provider_for(db, project, agent)
            if provider is None:
                return
            ctx = ProjectContext.from_project(project)
            ctx.session_id = session_id
            digest = totem_store.digest(
                ctx.memory_path, task="Continue after a background task"
            )
            system = build_system_prompt(
                ctx,
                agents_md=project.agents_md,
                memory_context=digest.get("context", ""),
                user_task="Continue after a background task",
                extra_context=settings.prompt_context(db),
            )
            if agent and agent.system_prompt:
                system += f"\n\n## Agent instructions\n{agent.system_prompt}"
            system += "\n\n" + BACKGROUND_NOTE
            registry = build_registry(writes=bool(project.allow_git_writes), db=db)
            client = provider_client(
                provider,
                provider.model,
                db=db,
                reasoning_effort=getattr(provider, "reasoning_effort", None),
            )
            messages = _replay(db, session_id, system)
            final = ""
            async for event in agent_loop.run_turn(
                ctx, client, registry, messages
            ):
                if event["type"] == "message":
                    final = event.get("content", "")
                elif event["type"] == "error":
                    return
            if final.strip():
                db.add(Message(session_id=session_id, role="assistant", content=final))
                db.commit()
                notify.send(
                    "Agent continued after a background task",
                    final[:400],
                    tags=["robot"],
                    url=settings.notification_url(
                        f"/p/{project_id}/chat?session={session_id}"
                    ),
                )
    except Exception:
        logger.exception("background continuation failed")
    finally:
        mark_idle(session_id)


def _reconcile() -> None:
    """Mark jobs left running by a previous process as lost."""
    with Session(engine()) as db:
        stale = db.exec(
            select(BackgroundTask).where(BackgroundTask.status == "running")
        ).all()
        for job in stale:
            job.status = "lost"
            job.error = "interrupted by restart"
            job.finished_at = _now()
            db.add(job)
        if stale:
            db.commit()


manager = JobManager()
