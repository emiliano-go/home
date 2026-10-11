"""Chat endpoint: SSE-streamed agent turn with Totem bootstrapping."""

import asyncio
import json
import logging
import os
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from hestia import actions, jobs, questions, runs, settings, skills, totem_store, usage
from hestia.agent import compaction
from hestia.agent import instructions
from hestia.agent import loop as agent_loop
from hestia.agent import reminders
from hestia.agent.prompt import build_system_prompt, compact_messages
from hestia.decision import scoring
from hestia.decision.service import DecisionService, EvaluateInput
from hestia.providers.base import provider_client, resolve_api_key, resolve_small_model
from hestia.registry.db import engine, session
from hestia.registry.models import AgentConfig, Message, Project, Provider, Session as ChatSession
from hestia.tools import build_registry, subagents
from hestia.tools import browser as browser_tools
from hestia.tools import goals as goal_tools
from hestia.tools import images as image_tools
from hestia.tools import questions as question_tools
from hestia.tools import reminders as reminder_tools
from hestia.tools import tasks as task_tools
from hestia.tools import watches as watch_tools
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["chat"])

logger = logging.getLogger("hestia.chat")
HEARTBEAT_SECONDS = float(os.environ.get("HESTIA_SSE_HEARTBEAT", "15"))
MEMORY_TOOLS = {"memory_create", "memory_update", "memory_delete", "memory_none"}
# Tools whose calls represent a change the decision engine should judge.
MUTATING_TOOLS = {
    "write_file",
    "workspace_write",
    "git_commit",
    "git_push",
    "git_create_branch",
    "gh_open_pr",
    "gh_merge_pr",
}
_CHAT_TASKS: set[asyncio.Task] = set()

_DELEGATION_NOTE = """\
## Delegation
You can delegate subtasks via run_subagent: read mode for exploration,
scanning, and review; write mode for workspace deliverables, memory curation,
and bulk file edits (doc sweeps, renames, typo fixes) when git writes are
enabled. For several parallel agents, use run_swarm with one shared directive
plus a specific task per agent (1 to 8 agents), optionally detached with
run_in_background. Both tools accept an optional write_scope: a list of repo
or workspace globs the subagent may write (e.g. ['src/audit/**']); anything
outside is refused, so you can fixate what each agent may touch. Prefer an
action (explore, github-scan, memory-keeper, writer, code-reviewer, bulk-edit)
so the app uses the agent assigned to that role; list profiles with
agent_list. Send large mechanical edits to a cheap bulk-edit agent, then
review the diff and commit/push/open the PR yourself: subagents can edit files
but never run mutating git commands. Images, the browser, the task board,
automations, and notifications are yours alone too."""

_GOAL_NOTE = """\
## Goal mode
This conversation is about a project goal. Interview the user to clarify the
outcome with focused questions (one or two at a time) and keep the draft spec at
the path from the first message updated with workspace_write. Do not build the
board yourself; when the goal is clear, tell the user to press "Generate board"
on the Goals tab."""

_USER_NOTE = """\
## About the owner
The owner's name and standing preferences are in your context. When the owner
tells you how to address them, call set_owner_name. When they state a durable
rule or quirk about how to respond (tone, format, length, things to avoid),
call remember_preference. Apply every standing preference without being
reminded, and never re-ask for something already remembered. When you are
blocked on a manual step only the owner can do (a sudo command, signing a
commit with GPG, logging in somewhere), call user_required with the exact
command; the turn ends until they confirm."""

_BACKGROUND_NOTE = """\
## Background tasks
Long jobs can run in the background: call start_background_task (or
run_subagent with run_in_background=true) with a short description. It returns
a task id immediately; keep working or stop, and a notification arrives when
it finishes (messages tagged [background task]). Use job_list and job_output
for a quick status check and job_stop to cancel; do not poll in a loop."""

CHECKPOINT_PROMPT = """\
Memory checkpoint. Before this turn ends, record what future sessions must
know, and nothing else:
- memory_create for durable engineering facts: decisions (include rationale),
  gotchas, invariants (include verificationMethod), contracts, constraints,
  bugs, architecture (metadata: component).
- Required metadata: architecture (component), implementation (subject, kind,
  path), assumption (claimCategory, basis); evidence entries need path,
  startLine, endLine, contentHash.
- memory_update to correct an existing memory instead of duplicating it.
- If there is genuinely nothing durable, call memory_none with a one-line reason.
Do not restate the conversation; write only what survived it."""

MEMORY_WRITER_PROMPT = """\
You are the memory writer for this project. Read the finished turn below and
store only what future sessions need:
- memory_create for durable engineering facts (decision + rationale, gotcha,
  invariant + verificationMethod, contract, constraint, bug, architecture).
- Required metadata: architecture (component), implementation (subject, kind,
  path), assumption (claimCategory, basis); evidence entries need path,
  startLine, endLine, contentHash.
- memory_candidate for uncertain or lower-confidence items (observations,
  hypotheses, assumptions, ambiguities).
- memory_update to correct an existing memory instead of duplicating it.
- If nothing is durable, call memory_none.
Never store the raw conversation."""

_BROWSER_NOTE = """\
## Browser
You have a real browser. Use browser_task for autonomous multi-step web goals
(filling forms, extracting data) and browser_open / browser_screenshot /
browser_get_content / browser_click / browser_type / browser_eval for UI
debugging on a persistent session; browser_close frees it. Local dev servers
need the project's "local browser" toggle. Prefer web_fetch for reading a
single static page."""

_DECISION_NOTE = """\
## Decision engine
A decision engine evaluates each finished turn. If it cannot confirm the change
answers the request, it returns corrective feedback as your next instruction:
address it with minimal edits, run the relevant checks, and report the results.
A deterministic verify lane also vetoes secrets, injection, destructive
commands, and failing tests/typechecks."""


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _replay_messages(rows, system: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in rows:
        if m.role == "assistant":
            msg: dict = {"role": "assistant", "content": m.content}
            if getattr(m, "thinking", None):
                # Thinking models require their reasoning echoed back.
                msg["reasoning_content"] = m.thinking
            if m.tool_calls:
                try:
                    msg["tool_calls"] = json.loads(m.tool_calls)
                except ValueError:
                    msg["tool_calls"] = []
            messages.append(msg)
        elif m.role == "tool":
            messages.append(
                {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
            )
        elif m.role == "notification":
            messages.append({"role": "user", "content": f"[background task]\n{m.content}"})
        else:
            messages.append({"role": m.role, "content": m.content})
    return messages


def _sse_run(event: dict) -> str:
    payload = {k: v for k, v in event.items() if k != "type"}
    payload["event"] = event["type"]
    return f"id: {event.get('seq', 0)}\ndata: {json.dumps(payload, default=str)}\n\n"


def _explicit_memory_writer(s: Session):
    """The agent explicitly assigned to the memory-writer action, or None."""
    from hestia.registry.models import ActionDefault, AgentConfig

    row = s.get(ActionDefault, "memory-writer")
    if row is None or not row.agent_id:
        return None
    return s.get(AgentConfig, row.agent_id)


def _candidate_from_turn(s: Session, ctx, user_text: str, full_text: str, source: str) -> None:
    """Last resort: a conversation excerpt as a low-confidence candidate."""
    from hestia.registry.models import MemoryCandidate

    title = f"Turn: {(user_text.strip().splitlines() or [''])[0][:70]}"
    statement = f"Q: {user_text.strip()[:1200]}\n\nA: {full_text.strip()[:1200]}"
    s.add(
        MemoryCandidate(
            project_id=ctx.project_id,
            session_id=ctx.session_id,
            run_id=ctx.run_id,
            type="observation",
            title=title,
            statement=statement,
            tags=json.dumps(["conversation"]),
            confidence=0.3,
            source=source,
        )
    )
    s.commit()


async def _memory_checkpoint(
    run, ctx, client, registry, messages, tokens
) -> tuple[int, int, bool]:
    """Blocking memory step: the agent must write memory or acknowledge none."""
    checkpoint = messages + [{"role": "user", "content": CHECKPOINT_PROMPT}]
    writes = candidates = 0
    acked = False
    async for event in agent_loop.run_turn(ctx, client, registry, checkpoint, run=run):
        etype = event["type"]
        if etype == "usage":
            usage.merge(tokens, event.get("usage"))
            runs.manager.emit(run, event)
            continue
        if etype == "tool_call":
            name = event.get("name")
            if name in ("memory_create", "memory_update"):
                writes += 1
            elif name == "memory_candidate":
                candidates += 1
            elif name == "memory_none":
                acked = True
        runs.manager.emit(run, event)
        if etype in ("stopped", "timed_out"):
            break
    return writes, candidates, acked


def _dispatch_memory_writer(run, project, chat_session, user_text: str, full_text: str, agent_id: int) -> None:
    writer_run = runs.manager.create(
        "memory-writer",
        project_id=project.id,
        session_id=chat_session.id,
        parent_run_id=run.id,
        title=f"Memory: {user_text[:60]}",
    )
    task = asyncio.create_task(
        _execute_memory_writer(writer_run, project.id, chat_session.id, user_text, full_text, agent_id)
    )
    _CHAT_TASKS.add(task)
    task.add_done_callback(_CHAT_TASKS.discard)


async def _execute_memory_writer(writer_run, project_id: int, session_id: str, user_text: str, full_text: str, agent_id: int) -> None:
    status, error = "done", ""
    try:
        with Session(engine()) as s:
            project = s.get(Project, project_id)
            config = s.get(AgentConfig, agent_id) if agent_id else None
            if project is None or config is None:
                runs.manager.finish(writer_run, "error", error="memory writer profile missing")
                return
            provider = s.get(Provider, config.provider_id)
            if provider is None:
                runs.manager.finish(writer_run, "error", error="memory writer has no provider")
                return
            provider = actions.effective_provider(config, provider)
            ctx = ProjectContext.from_project(project)
            ctx.session_id = session_id
            ctx.run_id = writer_run.id
            client = provider_client(
                provider,
                resolve_small_model(provider),
                db=s,
                session=f"memory-{writer_run.id}",
                reasoning_effort=getattr(provider, "reasoning_effort", None),
            )
            registry = build_registry(db=s).filtered(["memory"])
            turn = (
                f"## User\n{user_text.strip()[:4000]}\n\n"
                f"## Assistant\n{full_text.strip()[:8000]}"
            )
            system = MEMORY_WRITER_PROMPT
            if config.system_prompt:
                system += f"\n\n## Agent instructions\n{config.system_prompt}"
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": turn},
            ]
            written = candidates = 0
            async for event in agent_loop.run_turn(ctx, client, registry, messages, run=writer_run):
                etype = event["type"]
                if etype == "tool_call":
                    if event.get("name") in ("memory_create", "memory_update"):
                        written += 1
                    elif event.get("name") == "memory_candidate":
                        candidates += 1
                elif etype in ("error", "stopped", "timed_out"):
                    status, error = etype, event.get("message", "")
                runs.manager.emit(writer_run, event)
            if written or candidates:
                s.add(
                    Message(
                        session_id=session_id,
                        role="notification",
                        content=f"Memory writer: {written} written, {candidates} candidates.",
                    )
                )
                s.commit()
    except Exception as e:  # noqa: BLE001
        status, error = "error", f"{type(e).__name__}: {e}"
        logger.exception("memory writer failed")
    finally:
        runs.manager.finish(writer_run, status, error=error)


async def _evaluate_turn(run, ctx, chat_session, user_text, full_text, pending_turns):
    """Evaluate a completed turn with the decision engine (no-op when disabled)."""
    mutations: list[dict] = []
    grounding: list[dict] = []
    tool_calls: list[dict] = []
    for turn in pending_turns:
        for call in turn.get("calls", []):
            tool_calls.append(call)
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = function.get("name") or call.get("name")
            raw = function.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                args = {}
            if name in MUTATING_TOOLS:
                path = args.get("path") or args.get("file_path") or args.get("filePath")
                mutations.append(
                    {
                        "tool": name,
                        "input": raw if isinstance(raw, str) else json.dumps(args),
                        "output": "",
                        "paths": [path] if path else [],
                    }
                )
        for result in turn.get("results", []):
            grounding.append({"tool": result.get("name"), "output": str(result.get("preview", ""))[:2000]})
    return await DecisionService().evaluate(
        EvaluateInput(
            task=user_text,
            assistant_text=full_text,
            tool_calls=tool_calls,
            mutations=mutations,
            grounding=grounding,
            session_id=chat_session.id,
            project_dir=ctx.memory_path,
            cwd=ctx.local_path,
        )
    )


async def _execute_chat(
    run,
    project_id: int,
    session_id: str,
    user_text: str,
    agent_id: int | None,
    provider_id: int | None,
    action_key: str,
) -> None:
    """Run one chat turn to completion, independently of any client."""
    status, error, full_text = "done", "", ""
    jobs.mark_active(session_id)
    try:
        with Session(engine()) as s:
            project = s.get(Project, project_id)
            chat_session = s.get(ChatSession, session_id)
            if project is None or chat_session is None:
                runs.manager.finish(run, "error", error="project or session no longer exists")
                return
            agent_config = (
                s.get(AgentConfig, agent_id) if agent_id else actions.resolve_action(s, action_key)
            )
            provider = s.get(Provider, provider_id)
            if provider is None:
                runs.manager.finish(run, "error", error="no provider configured")
                return
            provider = actions.effective_provider(agent_config, provider)
            ctx = ProjectContext.from_project(project)
            ctx.session_id = chat_session.id
            ctx.run_id = run.id
            sandbox_info = None
            sandbox_root = None
            if ctx.write_mode == "yolo":
                try:
                    from hestia import sandbox

                    refs = ctx.repos or [ref for ref in [ctx.primary_repo()] if ref]
                    sandbox_root = ctx.memory_path
                    sandbox_info = sandbox.create([(ref.alias, ref.local_path) for ref in refs], label=f"turn {chat_session.id}")
                    for ref in refs:
                        ref.local_path = Path(sandbox_info["repos"][ref.alias])
                    if refs:
                        ctx.local_path = refs[0].local_path
                    ctx.memory_override = sandbox_root
                except Exception:  # noqa: BLE001
                    logger.exception("sandbox creation failed; running against the clone")
                    sandbox_info = None
            elif ctx.write_mode != "read":
                try:
                    from hestia import snapshots

                    snapshots.create(ctx.memory_path, label=f"turn {chat_session.id}")
                except Exception:  # noqa: BLE001
                    logger.exception("snapshot failed")
            client = provider_client(
                provider,
                provider.model,
                db=s,
                session=f"chat-{chat_session.id}",
                reasoning_effort=getattr(provider, "reasoning_effort", None),
            )
            registry = build_registry(writes=ctx.write_mode != "read", db=s)
            for tool in image_tools.make_tools(provider):
                registry.register(tool)
            browser_ready = browser_tools.available()
            if browser_ready:
                for tool in browser_tools.make_tools(provider, s):
                    registry.register(tool)
            for tool in subagents.make_tools(s):
                registry.register(tool)
            for tool in task_tools.make_tools(s):
                registry.register(tool)
            for tool in goal_tools.make_tools(s):
                registry.register(tool)
            for tool in question_tools.make_tools(s):
                registry.register(tool)
            for tool in reminder_tools.make_tools(s):
                registry.register(tool)
            for tool in watch_tools.make_tools(s):
                registry.register(tool)

            decision_settings = DecisionService().settings()
            digest = totem_store.digest(ctx.memory_path, task=user_text)
            system = build_system_prompt(
                ctx,
                agents_md=instructions.load(ctx.memory_path, fallback=project.agents_md),
                memory_context=digest.get("context", ""),
                user_task=user_text,
                writes_enabled=bool(project.allow_git_writes),
                extra_context=settings.prompt_context(s),
                skills_context=skills.summary(),
            )
            if agent_config and agent_config.system_prompt:
                system += f"\n\n## Agent instructions\n{agent_config.system_prompt}"
            system += "\n\n" + _DELEGATION_NOTE
            system += "\n\n" + _USER_NOTE
            system += "\n\n" + _BACKGROUND_NOTE
            if browser_ready:
                system += "\n\n" + _BROWSER_NOTE
            if action_key == "goal":
                system += "\n\n" + _GOAL_NOTE
            if decision_settings.enabled and decision_settings.help:
                system += "\n\n" + _DECISION_NOTE

            rows = s.exec(
                select(Message)
                .where(Message.session_id == chat_session.id)
                .order_by(Message.id)
            ).all()
            messages = _replay_messages(rows, system)
            messages, compacted = compaction.compact(
                messages,
                token_budget=int(os.environ.get("HESTIA_COMPACT_TOKENS", compaction.DEFAULT_BUDGET_TOKENS)),
                keep_recent_tools=int(os.environ.get("HESTIA_COMPACT_KEEP", compaction.DEFAULT_KEEP_TOOLS)),
            )
            if compacted:
                runs.manager.emit(run, {"type": "compaction", "tokens": compaction.estimate_tokens(messages)})
            messages = reminders.apply(
                messages,
                plan_mode=bool(ctx.require_plan and ctx.write_mode != "read"),
                decision=bool(decision_settings.enabled),
            )

            tokens: dict = {}
            pending_turns: list[dict] = []
            pending_thinking: list[str] = []
            full_thinking = ""
            paused = False
            full_text = ""
            memory_writes = 0
            memory_candidates = 0
            memory_acked = False
            retries_left = decision_settings.max_feedback_retries if decision_settings.enabled else 0

            while True:
                pending_turns = []
                pending_thinking = []
                full_thinking = ""
                full_text = ""
                paused = False
                async for event in agent_loop.run_turn(ctx, client, registry, messages, run=run):
                    etype = event["type"]
                    if etype == "usage":
                        usage.merge(tokens, event.get("usage"))
                        runs.manager.emit(run, event)
                        continue
                    if etype == "thinking":
                        pending_thinking.append(event.get("text") or "")
                    if etype == "tool_call":
                        name = event.get("name")
                        if name in ("memory_create", "memory_update"):
                            memory_writes += 1
                        elif name == "memory_candidate":
                            memory_candidates += 1
                        elif name == "memory_none":
                            memory_acked = True
                    if etype == "question":
                        asked = event.get("question", "")
                        full_text = f"{full_text}\n\n{asked}".strip() if full_text else asked
                        pending_turns = []
                        pending_thinking = []
                        paused = True
                    elif etype == "message":
                        calls = event.get("tool_calls") or []
                        if calls:
                            pending_turns.append(
                                {
                                    "content": event.get("content") or "",
                                    "calls": calls,
                                    "results": [],
                                    "thinking": "".join(pending_thinking),
                                }
                            )
                            pending_thinking = []
                        elif event.get("content"):
                            full_text = event["content"]
                            full_thinking = "".join(pending_thinking)
                            pending_thinking = []
                    elif etype == "tool_result" and pending_turns:
                        pending_turns[-1]["results"].append(event)
                    if etype in ("error", "stopped", "timed_out"):
                        status = etype
                        error = event.get("message", "")
                    runs.manager.emit(run, event)
                    if etype in ("stopped", "timed_out"):
                        break

                # Persist complete tool turns so reloads keep the chips and the next
                # turn replays valid assistant/tool pairs to the provider.
                for turn in pending_turns:
                    if paused or len(turn["results"]) != len(turn["calls"]):
                        continue
                    s.add(
                        Message(
                            session_id=chat_session.id,
                            role="assistant",
                            content=turn["content"],
                            thinking=turn.get("thinking") or None,
                            tool_calls=json.dumps(turn["calls"]),
                        )
                    )
                    for result in turn["results"]:
                        s.add(
                            Message(
                                session_id=chat_session.id,
                                role="tool",
                                name=result.get("name"),
                                tool_call_id=result.get("id"),
                                ok=result.get("ok"),
                                content=str(result.get("preview", ""))[:20_000],
                            )
                        )
                if full_text.strip():
                    s.add(
                        Message(
                            session_id=chat_session.id,
                            role="assistant",
                            content=full_text,
                            thinking=full_thinking or None,
                        )
                    )
                s.commit()

                evaluation = None
                if status == "done" and full_text.strip():
                    try:
                        evaluation = await _evaluate_turn(run, ctx, chat_session, user_text, full_text, pending_turns)
                    except Exception:  # noqa: BLE001
                        logger.exception("decision evaluation failed")
                        evaluation = None
                    if evaluation is not None:
                        runs.manager.emit(
                            run,
                            {
                                "type": "decision",
                                "kind": evaluation.kind,
                                "verdict": evaluation.verdict,
                                "composite": evaluation.composite,
                                "vetoes": evaluation.vetoes,
                            },
                        )
                if evaluation is None or evaluation.verdict == "pass" or paused:
                    break
                if retries_left <= 0:
                    break
                retries_left -= 1
                feedback_text = (
                    scoring.review_feedback(
                        composite=evaluation.composite,
                        threshold=decision_settings.pass_threshold,
                        failures=evaluation.failures,
                        vetoes=evaluation.vetoes,
                        findings=evaluation.findings,
                    )
                    if evaluation.verdict == "needs_review"
                    else scoring.feedback(
                        composite=evaluation.composite,
                        threshold=decision_settings.pass_threshold,
                        failures=evaluation.failures,
                        findings=evaluation.findings,
                    )
                )
                s.add(Message(session_id=chat_session.id, role="user", content=feedback_text))
                s.commit()
                messages.append({"role": "user", "content": feedback_text})
                runs.manager.emit(run, {"type": "message", "content": feedback_text, "synthetic": True})

            if sandbox_info is not None:
                try:
                    from hestia import sandbox

                    patches = {
                        alias: sandbox.patch(Path(path), sandbox_info["base"][alias])
                        for alias, path in sandbox_info["repos"].items()
                    }
                    sandbox.record(sandbox_root, sandbox_info, patches)
                    changed = {
                        alias: len([line for line in text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))])
                        for alias, text in patches.items()
                        if text.strip()
                    }
                    runs.manager.emit(
                        run,
                        {
                            "type": "sandbox",
                            "path": sandbox_info["path"],
                            "changed": changed,
                            "empty": not changed,
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("sandbox capture failed")

            usage.record(
                s,
                project.id,
                session_id=chat_session.id,
                action="chat",
                model=provider.model,
                usage=tokens,
            )
            memory_used = bool(memory_writes or memory_candidates or memory_acked)
            if full_text.strip() and status == "done" and not memory_used and not paused:
                writer = _explicit_memory_writer(s)
                if writer is not None:
                    _dispatch_memory_writer(
                        run, project, chat_session, user_text, full_text, writer.id
                    )
                    runs.manager.emit(run, {"type": "memory", "writer": True, "written": 0})
                else:
                    memory_writes, memory_candidates, memory_acked = await _memory_checkpoint(
                        run, ctx, client, registry, messages, tokens
                    )
                    if not (memory_writes or memory_candidates or memory_acked):
                        _candidate_from_turn(s, ctx, user_text, full_text, "checkpoint")
                        memory_candidates = 1
                    runs.manager.emit(
                        run,
                        {
                            "type": "memory",
                            "checkpoint": True,
                            "written": memory_writes,
                            "candidates": memory_candidates,
                        },
                    )
    except Exception as e:  # noqa: BLE001
        status, error = "error", f"{type(e).__name__}: {e}"
        logger.exception("chat run failed")
    finally:
        if run.cancelled and status == "done":
            status = "stopped"
        runs.manager.finish(run, status, result=full_text, error=error)
        jobs.mark_idle(session_id)


@router.post("/projects/{project_id}/chat")
async def chat(project_id: int, body: dict, s: Session = Depends(session)):
    """Start a chat turn as a run; the response streams the run's events.

    The run keeps going if the client disconnects; re-attach with
    ``GET /api/runs/{run_id}/events`` (Last-Event-ID) to replay.
    """
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    user_text = (body.get("message") or "").strip()
    if not user_text:
        raise HTTPException(400, "message is required")

    chat_session = None
    if body.get("session_id"):
        chat_session = s.get(ChatSession, body["session_id"])
        if chat_session and chat_session.project_id != project.id:
            raise HTTPException(404, "session not found")

    agent_config = None
    action_key = (
        body.get("action") or (chat_session.action if chat_session else None) or "chat"
    ).strip()
    if action_key not in actions.ACTIONS_BY_KEY:
        action_key = "chat"
    if body.get("agent_id"):
        agent_config = s.get(AgentConfig, body["agent_id"])
        if not agent_config:
            raise HTTPException(404, "agent profile not found")
    else:
        agent_config = actions.resolve_action(s, action_key)
    if agent_config:
        provider = s.get(Provider, agent_config.provider_id)
    else:
        provider_id = body.get("provider_id") or project.default_provider_id
        provider = s.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent_config, provider)
    if not provider:
        raise HTTPException(400, "no provider configured for this project")

    if chat_session is None:
        title = (user_text.splitlines()[0].strip() or "New session")[:60]
        chat_session = ChatSession(project_id=project.id, title=title, action=action_key)
        s.add(chat_session)
        s.commit()
        s.refresh(chat_session)

    s.add(Message(session_id=chat_session.id, role="user", content=user_text))
    chat_session.updated_at = datetime.now(timezone.utc)
    s.add(chat_session)
    s.commit()

    # A user message answers every open question in this session.
    for pending in questions.open_for_session(s, chat_session.id):
        questions.answer(s, pending, user_text)

    run = runs.manager.create(
        "chat", project_id=project.id, session_id=chat_session.id, title=user_text
    )
    runs.manager.emit(run, {"type": "session", "session_id": chat_session.id})
    task = asyncio.create_task(
        _execute_chat(
            run,
            project.id,
            chat_session.id,
            user_text,
            agent_config.id if agent_config else None,
            provider.id,
            action_key,
        )
    )
    _CHAT_TASKS.add(task)
    task.add_done_callback(_CHAT_TASKS.discard)

    async def stream():
        async for event in runs.manager.subscribe(run, 0):
            if event.get("type") == "ping":
                yield ": ping\n\n"
                continue
            yield _sse_run(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


_BTW_PROMPT = """\
You are the project agent for '{name}', answering a quick side question while
the main task keeps running. You get a compacted excerpt of the conversation,
not the full history; you can read the repository with your read-only tools
when you need to. Reply briefly and directly (a few sentences or a short
list). Do not take actions or change anything. If the excerpt is not enough,
say what you would need.

## Compacted context
{context}
"""

_BTW_MAX_TURNS = 4
_BTW_GROUPS = ["repo", "files", "github"]


@router.post("/projects/{project_id}/btw")
def btw(project_id: int, body: dict, s: Session = Depends(session)):
    """Side question while the main task keeps running: SSE token stream.

    The same agent answers with read-only tools, primed with the compacted
    context the client sends (falling back to the session transcript).
    """
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")

    chat_session = None
    if body.get("session_id"):
        chat_session = s.get(ChatSession, body["session_id"])
        if chat_session and chat_session.project_id != project.id:
            raise HTTPException(404, "session not found")
    action_key = (chat_session.action if chat_session else "chat") or "chat"
    if action_key not in actions.ACTIONS_BY_KEY:
        action_key = "chat"
    agent_config = None
    if body.get("agent_id"):
        agent_config = s.get(AgentConfig, body["agent_id"])
        if not agent_config:
            raise HTTPException(404, "agent profile not found")
    else:
        agent_config = actions.resolve_action(s, action_key)
    if agent_config:
        provider = s.get(Provider, agent_config.provider_id)
    else:
        provider_id = body.get("provider_id") or project.default_provider_id
        provider = s.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent_config, provider)
    if not provider:
        raise HTTPException(400, "no provider configured for this project")

    context = ""
    if isinstance(body.get("context"), list):
        context = compact_messages(body["context"])
    if not context and chat_session:
        rows = s.exec(
            select(Message)
            .where(Message.session_id == chat_session.id)
            .order_by(Message.id)
        ).all()
        context = compact_messages(rows)
    system = _BTW_PROMPT.format(name=project.name, context=context or "(no context yet)")

    ctx = ProjectContext.from_project(project)
    ctx.session_id = chat_session.id if chat_session else None
    client = provider_client(
        provider,
        provider.model,
        db=s,
        session=f"btw-{chat_session.id if chat_session else project.id}",
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    registry = build_registry().filtered(_BTW_GROUPS).readonly()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]

    async def _stream_impl():
        tokens: dict = {}
        queue: asyncio.Queue = asyncio.Queue()

        async def pump():
            try:
                async for event in agent_loop.run_turn(
                    ctx, client, registry, messages, max_turns=_BTW_MAX_TURNS
                ):
                    await queue.put(event)
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                etype = event["type"]
                if etype == "usage":
                    usage.merge(tokens, event.get("usage"))
                elif etype == "token":
                    yield _sse({"event": "token", "text": event.get("text", "")})
                elif etype == "error":
                    yield _sse({"event": "error", "message": event.get("message", "")})
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        usage.record(
            s,
            project.id,
            session_id=chat_session.id if chat_session else None,
            action="btw",
            model=provider.model,
            usage=tokens,
        )
        yield _sse({"event": "done"})

    return StreamingResponse(_stream_impl(), media_type="text/event-stream")
