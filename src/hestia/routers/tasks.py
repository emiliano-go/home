"""Kanban task board: per-project CRUD, independent of chat sessions."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from hestia import actions, issuesync, settings, taskboard, totem_store, usage
from hestia.agent import loop as agent_loop
from hestia.agent.prompt import build_system_prompt
from hestia.providers.base import OpenAIClient, resolve_api_key
from hestia.registry.db import session
from hestia.registry.models import Project, Provider, Task
from hestia.tools import build_registry
from hestia.tools import tasks as task_tools
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["tasks"])


def _project_or_404(project_id: int, s: Session) -> Project:
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return project


@router.get("/projects/{project_id}/tasks")
def list_tasks(project_id: int, ready: bool = False, s: Session = Depends(session)):
    _project_or_404(project_id, s)
    tasks = s.exec(
        select(Task).where(Task.project_id == project_id).order_by(Task.position, Task.id)
    ).all()
    blocked = taskboard.blocked_map(s, project_id)
    if ready:
        tasks = [t for t in tasks if t.id not in blocked and t.status != "done"]
    return [taskboard.as_dict(t, blocked.get(t.id)) for t in tasks]


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task(project_id: int, body: dict, s: Session = Depends(session)):
    _project_or_404(project_id, s)
    try:
        task = taskboard.create(
            s,
            project_id,
            title=body.get("title", ""),
            description=body.get("description", ""),
            status=body.get("status", "backlog"),
            priority=body.get("priority", "medium"),
            milestone_id=body.get("milestone_id"),
            depends_on=body.get("depends_on"),
            acceptance=body.get("acceptance", ""),
            source=body.get("source", "user"),
            due_at=body.get("due_at"),
            repo=body.get("repo"),
        )
    except taskboard.InvalidTask as e:
        raise HTTPException(400, str(e))
    return taskboard.as_dict(task, taskboard.blocked_map(s, project_id).get(task.id))


@router.put("/tasks/{task_id}")
def update_task(task_id: int, body: dict, s: Session = Depends(session)):
    task = s.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    try:
        taskboard.update(s, task, body)
    except taskboard.InvalidTask as e:
        raise HTTPException(400, str(e))
    return taskboard.as_dict(task, taskboard.blocked_map(s, task.project_id).get(task.id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, s: Session = Depends(session)):
    task = s.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    taskboard.delete(s, task)


@router.post("/projects/{project_id}/issues/sync")
def sync_issues(project_id: int, body: dict, s: Session = Depends(session)):
    """Push board tasks to GitHub issues (requires git writes + GITHUB_TOKEN)."""
    project = _project_or_404(project_id, s)
    try:
        return issuesync.sync_tasks(s, project, body.get("task_ids"), repo=body.get("repo"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / GitHub API
        raise HTTPException(502, f"could not create issues: {str(e)[:200]}")


SUGGEST_PROMPT = """\
Propose the next work for this project's board.

Read the current board with task_list and the project's Totem memory. Then
create between 2 and 5 tasks with task_create. Every task needs a short title,
a one-line description, acceptance criteria, and a priority; use depends_on
when ordering matters and due_at when a deadline is implied. Pass
source="suggested" on every task so the owner can
tell them apart. Do not duplicate existing tasks. End with a short plain-text
report of what you proposed and why.
"""


@router.post("/projects/{project_id}/tasks/suggest")
def suggest_tasks(project_id: int, body: dict, s: Session = Depends(session)):
    """One-shot agent run: propose next tasks into backlog, tagged suggested."""
    project = _project_or_404(project_id, s)
    agent = actions.resolve_action(s, "chat")
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
    registry = build_registry()
    for tool in task_tools.make_tools(s):
        registry.register(tool)
    digest = totem_store.digest(ctx.memory_path, task="Suggest next work")
    system = build_system_prompt(
        ctx,
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task="Suggest next work",
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + SUGGEST_PROMPT
    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        provider.model,
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "What should we do next?"},
    ]
    max_id = max(
        (t.id for t in s.exec(select(Task).where(Task.project_id == project_id)).all()),
        default=0,
    )

    async def run():
        final = ""
        tokens: dict = {}
        async for event in agent_loop.run_turn(
            ctx, client, registry, messages
        ):
            if event["type"] == "usage":
                usage.merge(tokens, event.get("usage"))
                continue
            if event["type"] == "message":
                final = event.get("content", "")
            if event["type"] == "error":
                return "", event["message"], tokens
        return final, None, tokens

    report, error, tokens = asyncio.run(run())
    usage.record(s, project.id, action="suggest", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)
    created = s.exec(
        select(Task).where(
            Task.project_id == project_id,
            Task.source == "suggested",
            Task.id > max_id,
        )
    ).all()
    return {"report": report, "task_ids": [t.id for t in created]}


@router.get("/tasks/{task_id}/comments")
def list_comments(task_id: int, s: Session = Depends(session)):
    if not s.get(Task, task_id):
        raise HTTPException(404, "task not found")
    return [
        {
            "id": c.id,
            "author": c.author,
            "body": c.body,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in taskboard.comments(s, task_id)
    ]


@router.post("/tasks/{task_id}/comments", status_code=201)
def create_comment(task_id: int, body: dict, s: Session = Depends(session)):
    task = s.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    try:
        comment = taskboard.add_comment(
            s, task, body.get("body", ""), author=body.get("author") or "you"
        )
    except taskboard.InvalidTask as e:
        raise HTTPException(400, str(e))
    return {
        "id": comment.id,
        "author": comment.author,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }
