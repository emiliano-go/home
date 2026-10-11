"""Kanban task board: shared constants and operations.

Tasks belong to a project and are independent of chat sessions. Both the REST
router and the agent's task_* tools go through here so validation and ordering
stay consistent. Tasks may depend on other tasks (``depends_on``, a JSON list
of ids); a task is "blocked" while any dependency is not done.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from hestia import events
from hestia.registry.models import Task, TaskComment

STATUSES = ["backlog", "todo", "doing", "review", "done"]
PRIORITIES = ["low", "medium", "high"]


class InvalidTask(ValueError):
    """Raised for invalid task input; mapped to HTTP 400 / tool errors."""


def parse_depends(value) -> list[int]:
    """Normalize a JSON string / list / None into a deduped list of task ids."""
    if value in (None, "", "[]"):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise InvalidTask("depends_on must be a JSON list of task ids")
    if not isinstance(value, (list, tuple)):
        raise InvalidTask("depends_on must be a list of task ids")
    out: list[int] = []
    for item in value:
        try:
            task_id = int(item)
        except (TypeError, ValueError):
            raise InvalidTask("depends_on must contain task ids")
        if task_id not in out:
            out.append(task_id)
    return out


def _would_cycle(tasks: dict[int, Task], task_id: int | None, deps: list[int]) -> bool:
    """DFS over the board with the proposed edges; True if a cycle appears."""
    graph = {tid: parse_depends(t.depends_on) for tid, t in tasks.items()}
    if task_id is not None:
        graph[task_id] = deps
    color: dict[int, int] = {}

    def visit(node: int) -> bool:
        state = color.get(node, 0)
        if state == 1:
            return True
        if state == 2:
            return False
        color[node] = 1
        for dep in graph.get(node, []):
            if dep in graph and visit(dep):
                return True
        color[node] = 2
        return False

    return any(visit(node) for node in list(graph))


def validate_depends(
    db: Session, project_id: int, task_id: int | None, deps: list[int]
) -> None:
    if not deps:
        return
    tasks = {
        t.id: t
        for t in db.exec(select(Task).where(Task.project_id == project_id)).all()
    }
    for dep in deps:
        if dep == task_id:
            raise InvalidTask("a task cannot depend on itself")
        if dep not in tasks:
            raise InvalidTask(f"unknown dependency task id: {dep}")
    if _would_cycle(tasks, task_id, deps):
        raise InvalidTask("dependency cycle between tasks")


def blocked_map(db: Session, project_id: int) -> dict[int, list[int]]:
    """task id -> unmet dependency ids (missing or not done)."""
    tasks = db.exec(select(Task).where(Task.project_id == project_id)).all()
    by_id = {t.id: t for t in tasks}
    out: dict[int, list[int]] = {}
    for task in tasks:
        blocked = [
            dep
            for dep in parse_depends(task.depends_on)
            if dep not in by_id or by_id[dep].status != "done"
        ]
        if blocked:
            out[task.id] = blocked
    return out


def _clean_repo(db: Session, project_id: int, repo) -> str | None:
    repo = (repo or "").strip()
    if not repo:
        return None
    from hestia import repos as repo_helpers

    aliases = {r.alias for r in repo_helpers.repos_for(db, project_id)}
    if repo not in aliases:
        raise InvalidTask(f"unknown repo alias: {repo}")
    return repo


def as_dict(task: Task, blocked_by: list[int] | None = None) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "milestone_id": task.milestone_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "position": task.position,
        "depends_on": parse_depends(task.depends_on),
        "blocked_by": blocked_by or [],
        "acceptance": task.acceptance or "",
        "source": task.source or "user",
        "github_issue": task.github_issue,
        "repo": task.repo,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "pr_url": task.pr_url,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def parse_due(value) -> datetime | None:
    """Parse an ISO date or datetime into an aware UTC datetime, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise InvalidTask("due_at must be an ISO date or datetime")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def at_risk(db: Session, project_id: int, within_hours: int = 48) -> list[Task]:
    """Open tasks overdue or due within the horizon, soonest first."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=within_hours)
    rows = db.exec(
        select(Task).where(
            Task.project_id == project_id,
            Task.status != "done",
            Task.due_at != None,  # noqa: E711
        )
    ).all()

    def aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    due = [t for t in rows if t.due_at and aware(t.due_at) <= horizon]
    return sorted(due, key=lambda t: aware(t.due_at))


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def next_ready(db: Session, project_id: int) -> Task | None:
    """Highest-priority unblocked task in todo or doing, or None."""
    blocked = blocked_map(db, project_id)
    rows = db.exec(
        select(Task).where(
            Task.project_id == project_id,
            Task.status.in_(("todo", "doing")),  # noqa: E712
        )
    ).all()
    ready = [t for t in rows if t.id not in blocked]

    def key(task: Task):
        due = datetime.max.replace(tzinfo=timezone.utc) if not task.due_at else (
            task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=timezone.utc)
        )
        return (PRIORITY_ORDER.get(task.priority, 1), due)

    ready.sort(key=key)
    return ready[0] if ready else None


def _clean(value: str | None, allowed: list[str], field: str, default: str) -> str:
    candidate = (value or default).strip().lower()
    if candidate not in allowed:
        raise InvalidTask(f"{field} must be one of: {', '.join(allowed)}")
    return candidate


def next_position(db: Session, project_id: int, status: str) -> float:
    rows = db.exec(
        select(Task).where(Task.project_id == project_id, Task.status == status)
    ).all()
    return max((t.position for t in rows), default=-1.0) + 1.0


def create(
    db: Session,
    project_id: int,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    milestone_id: int | None = None,
    depends_on=None,
    acceptance: str = "",
    source: str = "user",
    due_at=None,
    repo: str | None = None,
) -> Task:
    title = (title or "").strip()
    if not title:
        raise InvalidTask("title is required")
    status = _clean(status, STATUSES, "status", "backlog")
    priority = _clean(priority, PRIORITIES, "priority", "medium")
    deps = parse_depends(depends_on)
    validate_depends(db, project_id, None, deps)
    source = (source or "user").strip().lower()
    if source not in ("user", "suggested"):
        raise InvalidTask("source must be user or suggested")
    task = Task(
        project_id=project_id,
        milestone_id=milestone_id,
        repo=_clean_repo(db, project_id, repo),
        title=title,
        description=description or "",
        status=status,
        priority=priority,
        position=next_position(db, project_id, status),
        depends_on=json.dumps(deps),
        acceptance=acceptance or "",
        source=source,
        due_at=parse_due(due_at),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update(db: Session, task: Task, fields: dict) -> Task:
    old_status = task.status
    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise InvalidTask("title cannot be empty")
        task.title = title
    if "description" in fields:
        task.description = fields["description"] or ""
    if "acceptance" in fields:
        task.acceptance = fields["acceptance"] or ""
    if "repo" in fields:
        task.repo = _clean_repo(db, task.project_id, fields["repo"])
    if "status" in fields:
        new_status = _clean(fields["status"], STATUSES, "status", task.status)
        if (
            new_status == "done"
            and task.status != "done"
            and task.acceptance
            and not fields.get("reviewed")
        ):
            raise InvalidTask(
                "task has acceptance criteria; confirm the review (reviewed=true) to mark it done"
            )
        task.status = new_status
    if "priority" in fields:
        task.priority = _clean(fields["priority"], PRIORITIES, "priority", task.priority)
    if "position" in fields:
        try:
            task.position = float(fields["position"])
        except (TypeError, ValueError):
            raise InvalidTask("position must be a number")
    if "milestone_id" in fields:
        value = fields["milestone_id"]
        task.milestone_id = int(value) if value not in (None, "", 0) else None
    if "depends_on" in fields:
        deps = parse_depends(fields["depends_on"])
        validate_depends(db, task.project_id, task.id, deps)
        task.depends_on = json.dumps(deps)
    if "due_at" in fields:
        task.due_at = parse_due(fields["due_at"])
    if "pr_url" in fields:
        task.pr_url = (fields["pr_url"] or "").strip() or None
    if task.status != old_status and task.status in ("review", "done"):
        events.emit(
            db,
            task.project_id,
            "task_review" if task.status == "review" else "task_done",
            {"title": task.title},
            key=f"task:{task.id}:{task.status}",
        )
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def delete(db: Session, task: Task) -> None:
    """Delete a task and drop it from every other task's dependencies."""
    siblings = db.exec(select(Task).where(Task.project_id == task.project_id)).all()
    for other in siblings:
        deps = parse_depends(other.depends_on)
        if task.id in deps:
            other.depends_on = json.dumps([d for d in deps if d != task.id])
            other.updated_at = datetime.now(timezone.utc)
            db.add(other)
    comments = db.exec(select(TaskComment).where(TaskComment.task_id == task.id)).all()
    for comment in comments:
        db.delete(comment)
    db.delete(task)
    db.commit()


def comments(db: Session, task_id: int) -> list[TaskComment]:
    return db.exec(
        select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.id)
    ).all()


def add_comment(db: Session, task: Task, body: str, author: str = "you") -> TaskComment:
    body = (body or "").strip()
    if not body:
        raise InvalidTask("comment body is required")
    comment = TaskComment(task_id=task.id, author=(author or "you").strip(), body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
