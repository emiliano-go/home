"""Token usage accounting per project and session (tokens only, no pricing)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from hestia.registry.models import Project
from hestia.registry.models import Session as ChatSession
from hestia.registry.models import Usage


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_tokens(db: Session, project_id: int) -> dict:
    rows = db.exec(select(Usage).where(Usage.project_id == project_id)).all()
    start = _month_start()
    prompt = completion = runs = 0
    for row in rows:
        created = _aware(row.created_at)
        if created is None or created < start:
            continue
        prompt += row.prompt_tokens
        completion += row.completion_tokens
        runs += 1
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "tokens": prompt + completion,
        "runs": runs,
    }


def budget_state(db: Session, project: Project) -> dict:
    month = month_tokens(db, project.id)
    budget = project.token_budget
    percent = round(month["tokens"] / budget * 100) if budget else None
    return {
        "budget": budget,
        "enforced": bool(project.budget_enforced),
        "used": month["tokens"],
        "percent": percent,
        "over": bool(budget and month["tokens"] >= budget),
    }


def merge(total: dict, usage: dict | None) -> dict:
    """Add one provider turn's usage into an accumulating total."""
    if usage:
        total["prompt_tokens"] = total.get("prompt_tokens", 0) + int(usage.get("prompt_tokens") or 0)
        total["completion_tokens"] = total.get("completion_tokens", 0) + int(usage.get("completion_tokens") or 0)
    return total


def record(
    db: Session,
    project_id: int,
    *,
    action: str = "chat",
    model: str = "",
    usage: dict | None = None,
    session_id: str | None = None,
) -> None:
    """Store one agent run's token counts. No-ops when the provider sent none."""
    if not usage:
        return
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if prompt <= 0 and completion <= 0:
        return
    db.add(
        Usage(
            project_id=project_id,
            session_id=session_id,
            action=action,
            model=model or "",
            prompt_tokens=prompt,
            completion_tokens=completion,
        )
    )
    db.commit()


def summary(db: Session, project_id: int) -> dict:
    rows = db.exec(select(Usage).where(Usage.project_id == project_id)).all()
    by_action: dict[str, dict] = {}
    by_session: dict[int, dict] = {}
    total = {"prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "runs": 0}
    for row in rows:
        total["prompt_tokens"] += row.prompt_tokens
        total["completion_tokens"] += row.completion_tokens
        total["tokens"] += row.prompt_tokens + row.completion_tokens
        total["runs"] += 1

        action = by_action.setdefault(
            row.action, {"action": row.action, "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "runs": 0}
        )
        action["prompt_tokens"] += row.prompt_tokens
        action["completion_tokens"] += row.completion_tokens
        action["tokens"] += row.prompt_tokens + row.completion_tokens
        action["runs"] += 1

        if row.session_id:
            entry = by_session.setdefault(
                row.session_id, {"session_id": row.session_id, "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "runs": 0}
            )
            entry["prompt_tokens"] += row.prompt_tokens
            entry["completion_tokens"] += row.completion_tokens
            entry["tokens"] += row.prompt_tokens + row.completion_tokens
            entry["runs"] += 1

    titles = {
        s.id: s.title or "Untitled"
        for s in db.exec(
            select(ChatSession).where(ChatSession.project_id == project_id)
        ).all()
    }
    sessions = [
        {**entry, "title": titles.get(sid, f"session {sid}")}
        for sid, entry in by_session.items()
    ]
    sessions.sort(key=lambda s: s["tokens"], reverse=True)
    project = db.get(Project, project_id)
    return {
        "total": total,
        "month": month_tokens(db, project_id),
        "budget": budget_state(db, project) if project else None,
        "by_action": sorted(by_action.values(), key=lambda a: a["tokens"], reverse=True),
        "by_session": sessions,
    }
