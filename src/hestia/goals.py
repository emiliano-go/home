"""Project goals: a discussed outcome, its spec, and its planned board.

A goal links a chat session (the discussion), a workspace spec (``spec_path``),
and a milestone (the board grouping created when the goal is planned).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlmodel import Session, select

from hestia import milestones as milestones_mod
from hestia.registry.models import Goal, Milestone

STATUSES = ["drafting", "active", "done", "dropped"]


class InvalidGoal(ValueError):
    """Raised for invalid goal input; mapped to HTTP 400 / tool errors."""


def _clean_status(value: str | None, default: str) -> str:
    candidate = (value or default).strip().lower()
    if candidate not in STATUSES:
        raise InvalidGoal(f"status must be one of: {', '.join(STATUSES)}")
    return candidate


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60] or "goal"


def as_dict(goal: Goal, progress: dict | None = None) -> dict:
    return {
        "id": goal.id,
        "project_id": goal.project_id,
        "title": goal.title,
        "description": goal.description,
        "success_criteria": goal.success_criteria,
        "status": goal.status,
        "session_id": goal.session_id,
        "milestone_id": goal.milestone_id,
        "spec_path": goal.spec_path,
        "progress": progress,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


def progress(db: Session, goal: Goal) -> dict | None:
    if not goal.milestone_id:
        return None
    milestone = db.get(Milestone, goal.milestone_id)
    if milestone is None:
        return None
    return milestones_mod.progress(db, milestone)


def create(
    db: Session,
    project_id: int,
    title: str,
    description: str = "",
    success_criteria: str = "",
    status: str = "drafting",
) -> Goal:
    title = (title or "").strip()
    if not title:
        raise InvalidGoal("title is required")
    goal = Goal(
        project_id=project_id,
        title=title,
        description=description or "",
        success_criteria=success_criteria or "",
        status=_clean_status(status, "drafting"),
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update(db: Session, goal: Goal, fields: dict) -> Goal:
    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise InvalidGoal("title cannot be empty")
        goal.title = title
    if "description" in fields:
        goal.description = fields["description"] or ""
    if "success_criteria" in fields:
        goal.success_criteria = fields["success_criteria"] or ""
    if "status" in fields:
        goal.status = _clean_status(fields["status"], goal.status)
    if "session_id" in fields:
        goal.session_id = str(fields["session_id"]) if fields["session_id"] else None
    if "milestone_id" in fields:
        goal.milestone_id = int(fields["milestone_id"]) if fields["milestone_id"] else None
    if "spec_path" in fields:
        goal.spec_path = (fields["spec_path"] or "").strip() or None
    goal.updated_at = datetime.now(timezone.utc)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def delete(db: Session, goal: Goal) -> None:
    """Delete the goal; its milestone and tasks stay on the board."""
    db.delete(goal)
    db.commit()
