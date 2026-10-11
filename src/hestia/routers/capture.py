"""Capture: turn pasted notes into tasks, reminders, memories, and watches."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hestia import actions, settings, totem_store, usage
from hestia.agent.prompt import build_system_prompt
from hestia.agent.run import run_once
from hestia.registry.db import session
from hestia.registry.models import Project, Provider
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["capture"])

CAPTURE_PROMPT = """\
The owner pasted raw notes below (a message, meeting notes, an email, or a
thread). Turn it into durable structure, without inventing anything:
- Concrete action items become tasks with task_create: a one-line
  description, acceptance criteria, a priority, and due_at when a deadline is
  stated. Call task_list first and do not duplicate existing tasks.
- Time-based nudges become reminders with remind_me (resolve relative dates
  against the current time).
- Durable facts about clients or people go to memory_create tagged "client"
  and "client:<name>"; decisions go to memory_create too.
- If the notes imply an ongoing signal worth watching, add a watch.
End with a short plain-text report listing exactly what you created (task
ids, reminder texts, memory titles, watches).
"""


@router.post("/projects/{project_id}/capture")
async def capture(project_id: int, body: dict, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text is required")

    agent = actions.resolve_action(s, "capture")
    provider_id = (
        body.get("provider_id")
        or (agent.provider_id if agent else None)
        or project.default_provider_id
    )
    provider = s.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent, provider)
    if provider is None:
        raise HTTPException(400, "no provider configured for this project")

    ctx = ProjectContext.from_project(project)
    digest = totem_store.digest(ctx.memory_path, task="Capture notes")
    system = build_system_prompt(
        ctx,
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task="Capture notes",
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + CAPTURE_PROMPT
    groups = actions.ACTIONS_BY_KEY["capture"]["tools"]

    report, error, tokens = await run_once(
        project,
        provider,
        system,
        text,
        groups=groups,
        tasks_db=s,
    )
    usage.record(s, project.id, action="capture", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)
    return {"report": report}
