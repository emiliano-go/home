"""Background worker: due scheduled agent runs and inbox polling.

Runs inside the FastAPI lifespan. Schedules are serial (one agent run at a
time); a long run simply delays the next tick, which is fine for a
single-user cockpit.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from hestia import actions, events, inbox, notify, overview, reminders, repos, settings, taskboard, totem_store, usage, watchers
from hestia.agent.prompt import build_system_prompt
from hestia.agent.run import run_once
from hestia.registry.db import engine
from hestia.registry.models import Event, InboxItem, Project, Provider, Schedule, Task, Usage
from hestia.tools.registry import ProjectContext

TICK_SECONDS = max(5, int(os.environ.get("HESTIA_SCHEDULER_TICK", "30")))
INBOX_POLL_SECONDS = max(60, int(os.environ.get("HESTIA_INBOX_POLL_SECONDS", "600")))

logger = logging.getLogger("hestia.scheduler")

SCHEDULE_NOTE = """\

## Scheduled run
This is an unattended scheduled run. Do the job above and stop: write any
deliverable to the project workspace, keep it concise, and end with a short
plain-text report of what you did (it is shown on the Automations page).
"""


BRIEFING_PROMPT = """\
Write the commentary for today's briefing from the digest below.
Be concrete and brief (3 to 5 sentences): the single most important thing,
then the next two or three actions. No greeting, no filler.

## Digest
{digest}
"""


def _fmt_due(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.strftime("%b %d %H:%M UTC")


def _briefing_digest(db: Session) -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    soon = reminders.due(db, now + timedelta(days=1))
    if soon:
        items = "; ".join(f"{r.text} ({_fmt_due(r.due_at)})" for r in soon[:5])
        lines.append(f"Reminders: {items}")

    for project in db.exec(select(Project)).all():
        tasks = db.exec(select(Task).where(Task.project_id == project.id)).all()
        blocked = taskboard.blocked_map(db, project.id)
        ready = [
            t
            for t in tasks
            if t.status in ("todo", "doing", "review") and t.id not in blocked
        ]
        if ready:
            titles = ", ".join(f"#{t.id} {t.title}" for t in ready[:3])
            lines.append(f"{project.name} next up: {titles}")
        risky = taskboard.at_risk(db, project.id)
        if risky:
            items = "; ".join(
                f"#{t.id} {t.title} (due {t.due_at.date().isoformat()})"
                for t in risky[:4]
            )
            lines.append(f"{project.name} at risk: {items}")
        budget = usage.budget_state(db, project)
        if budget["budget"] and budget["percent"] is not None and budget["percent"] >= 80:
            lines.append(f"{project.name} token budget at {budget['percent']}%")

    unread = db.exec(select(InboxItem).where(InboxItem.read == False)).all()  # noqa: E712
    if unread:
        titles = ", ".join(i.title for i in unread[:3])
        lines.append(f"Inbox: {len(unread)} unread ({titles})")
    return "\n".join(lines)


def _first_provider_project(db: Session) -> Project | None:
    agent = actions.resolve_action(db, "chat")
    for project in db.exec(select(Project)).all():
        provider_id = (agent.provider_id if agent else None) or project.default_provider_id
        if provider_id and db.get(Provider, provider_id):
            return project
    return None


async def _maybe_send_briefing(db: Session) -> None:
    if not settings.get_bool(db, "briefing_enabled"):
        return
    local = settings.local_now(db)
    target = settings.get(db, "briefing_time") or "08:00"
    try:
        hh, mm = (int(part) for part in target.split(":"))
    except ValueError:
        hh, mm = 8, 0
    if (local.hour, local.minute) < (hh, mm):
        return
    today = local.date().isoformat()
    if settings.get(db, "briefing_last_sent") == today:
        return

    message = _briefing_digest(db) or "Nothing needs your attention today."
    if settings.get_bool(db, "briefing_agent"):
        project = _first_provider_project(db)
        if project is not None:
            agent = actions.resolve_action(db, "chat")
            provider_id = (agent.provider_id if agent else None) or project.default_provider_id
            provider = db.get(Provider, provider_id) if provider_id else None
            provider = actions.effective_provider(agent, provider)
            if provider is not None:
                digest = totem_store.digest(
                    repos.memory_root(project), task="Write the briefing commentary"
                )
                system = build_system_prompt(
                    ProjectContext.from_project(project),
                    agents_md=project.agents_md,
                    memory_context=digest.get("context", ""),
                    user_task="Write the briefing commentary",
                    extra_context=settings.prompt_context(db),
                )
                if agent and agent.system_prompt:
                    system += f"\n\n## Agent instructions\n{agent.system_prompt}"
                system += "\n\n" + BRIEFING_PROMPT.format(digest=message)
                report, error, tokens = await run_once(
                    project,
                    provider,
                    system,
                    "Write the briefing commentary.",
                    groups="workspace,repo,files",
                    tasks_db=db,
                )
                usage.record(
                    db, project.id, action="briefing", model=provider.model, usage=tokens
                )
                if report and not error:
                    message = f"{report.strip()}\n\n{message}"

    notify.send(
        "Morning briefing",
        message[:1800],
        tags=["sunrise"],
        url=settings.notification_url("/home"),
    )
    settings.set_many(db, {"briefing_last_sent": today})


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

DAILY_PLAN_PROMPT = """\
Write today's plan from the digest below. Rank the work by priority and
deadline, note anything blocked, and give 3 to 6 concrete steps. Write the
plan to the project workspace at plans/{date}.md with workspace_write, then
end with a short plain-text summary. Be brief, no greeting.

## Digest
{digest}
"""

WEEKLY_REVIEW_PROMPT = """\
Write this week's review from the digest below: what moved, what is blocked
or stale, and the velocity. Then propose next week's focus as 3 to 5 items.
Write it to the project workspace at reviews/{date}.md with workspace_write,
then end with a short plain-text summary. Be brief, no greeting.

## Digest
{digest}
"""


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        hh, mm = (int(part) for part in (value or "").split(":"))
        return hh, mm
    except ValueError:
        return default


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _due_key(task: Task) -> tuple[int, datetime]:
    return (
        PRIORITY_ORDER.get(task.priority, 1),
        _aware(task.due_at) if task.due_at else datetime.max.replace(tzinfo=timezone.utc),
    )


def _daily_plan_digest(db: Session) -> str:
    lines: list[str] = []
    soon = reminders.due(db, datetime.now(timezone.utc) + timedelta(days=1))
    if soon:
        lines.append(
            "Reminders: " + "; ".join(f"{r.text} ({_fmt_due(r.due_at)})" for r in soon[:5])
        )
    for project in db.exec(select(Project)).all():
        tasks = db.exec(select(Task).where(Task.project_id == project.id)).all()
        blocked = taskboard.blocked_map(db, project.id)
        ready = sorted(
            [t for t in tasks if t.status in ("todo", "doing") and t.id not in blocked],
            key=_due_key,
        )
        if ready:
            lines.append(
                f"{project.name} ready: "
                + ", ".join(f"#{t.id} {t.title}" for t in ready[:5])
            )
        risky = taskboard.at_risk(db, project.id)
        if risky:
            lines.append(
                f"{project.name} at risk: "
                + "; ".join(f"#{t.id} {t.title}" for t in risky[:3])
            )
    return "\n".join(lines)


def _weekly_review_digest(db: Session) -> str:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    lines: list[str] = []
    total_done = 0
    total_blocked = 0
    for project in db.exec(select(Project)).all():
        tasks = db.exec(select(Task).where(Task.project_id == project.id)).all()
        blocked = taskboard.blocked_map(db, project.id)
        done = [t for t in tasks if t.status == "done" and _aware(t.updated_at) >= start]
        blocked_open = [t for t in tasks if t.status != "done" and t.id in blocked]
        stale = [
            t
            for t in tasks
            if t.status in ("todo", "doing") and _aware(t.updated_at) < now - timedelta(days=14)
        ]
        total_done += len(done)
        total_blocked += len(blocked_open)
        lines.append(
            f"{project.name}: {len(done)} done this week, {len(blocked_open)} blocked, "
            f"{len(stale)} stale (>14d)"
        )
    week_runs = db.exec(select(Usage).where(Usage.created_at >= start)).all()
    tokens = sum(u.prompt_tokens + u.completion_tokens for u in week_runs)
    lines.insert(
        0,
        f"This week: {total_done} tasks done, {total_blocked} blocked, "
        f"{len(week_runs)} agent runs, {tokens} tokens.",
    )
    return "\n".join(lines)


async def _agent_narrative(db: Session, project: Project, digest: str, prompt: str) -> str | None:
    agent = actions.resolve_action(db, "chat")
    provider_id = (agent.provider_id if agent else None) or project.default_provider_id
    provider = db.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent, provider)
    if provider is None:
        return None
    system = build_system_prompt(
        ProjectContext.from_project(project),
        agents_md=project.agents_md,
        memory_context="",
        user_task="Write the plan",
        extra_context=settings.prompt_context(db),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + prompt.format(digest=digest, date=_now().date().isoformat())
    report, error, tokens = await run_once(
        project,
        provider,
        system,
        "Write it.",
        groups="workspace,repo,files,tasks",
        tasks_db=db,
    )
    usage.record(db, project.id, action="plan", model=provider.model, usage=tokens)
    return report if report and not error else None


async def _maybe_send_daily_plan(db: Session) -> None:
    if not settings.get_bool(db, "daily_plan_enabled"):
        return
    local = settings.local_now(db)
    hh, mm = _parse_hhmm(settings.get(db, "daily_plan_time") or "08:30", (8, 30))
    if (local.hour, local.minute) < (hh, mm):
        return
    today = local.date().isoformat()
    if settings.get(db, "daily_plan_last_sent") == today:
        return
    digest = _daily_plan_digest(db) or "Nothing scheduled today."
    message = digest
    project = _first_provider_project(db)
    if project is not None:
        narrative = await _agent_narrative(db, project, digest, DAILY_PLAN_PROMPT)
        if narrative:
            message = f"{narrative.strip()}\n\n{digest}"
    notify.send(
        "Daily plan",
        message[:1800],
        tags=["calendar"],
        url=settings.notification_url("/home"),
    )
    settings.set_many(db, {"daily_plan_last_sent": today})


async def _maybe_send_weekly_review(db: Session) -> None:
    if not settings.get_bool(db, "weekly_review_enabled"):
        return
    local = settings.local_now(db)
    try:
        day = int(settings.get(db, "weekly_review_day") or "4")
    except ValueError:
        day = 4
    if local.weekday() != day:
        return
    hh, mm = _parse_hhmm(settings.get(db, "weekly_review_time") or "16:00", (16, 0))
    if (local.hour, local.minute) < (hh, mm):
        return
    today = local.date().isoformat()
    if settings.get(db, "weekly_review_last_sent") == today:
        return
    digest = _weekly_review_digest(db) or "No activity recorded this week."
    message = digest
    project = _first_provider_project(db)
    if project is not None:
        narrative = await _agent_narrative(db, project, digest, WEEKLY_REVIEW_PROMPT)
        if narrative:
            message = f"{narrative.strip()}\n\n{digest}"
    notify.send(
        "Weekly review",
        message[:1800],
        tags=["bar_chart"],
        url=settings.notification_url("/home"),
    )
    settings.set_many(db, {"weekly_review_last_sent": today})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def as_dict(schedule: Schedule) -> dict:
    return {
        "id": schedule.id,
        "project_id": schedule.project_id,
        "action": schedule.action,
        "instruction": schedule.instruction,
        "interval_minutes": schedule.interval_minutes,
        "enabled": schedule.enabled,
        "trigger": schedule.trigger or "interval",
        "event": schedule.event or "",
        "event_filter": schedule.event_filter or "",
        "cooldown_minutes": schedule.cooldown_minutes or 0,
        "last_run_at": overview._iso(schedule.last_run_at),
        "last_status": schedule.last_status,
        "last_report": schedule.last_report,
        "created_at": overview._iso(schedule.created_at),
    }


def due_schedules(db: Session, now: datetime | None = None) -> list[Schedule]:
    now = _naive(now or _now())
    due = []
    for schedule in db.exec(
        select(Schedule).where(
            Schedule.enabled == True,  # noqa: E712
            Schedule.trigger != "event",
        )
    ).all():
        last = _naive(schedule.last_run_at) or _naive(schedule.created_at) or now
        if now - last >= timedelta(minutes=max(1, schedule.interval_minutes)):
            due.append(schedule)
    return due


async def run_schedule(schedule_id: int, event: dict | None = None) -> dict | None:
    """Run one schedule now and record the outcome. Returns its state or None.

    When ``event`` is given (an event-triggered run), the event kind, title, and
    url are substituted into the instruction.
    """
    with Session(engine()) as db:
        schedule = db.get(Schedule, schedule_id)
        if not schedule:
            return None
        project = db.get(Project, schedule.project_id)
        if not project:
            db.delete(schedule)
            db.commit()
            return None

        agent = actions.resolve_action(db, schedule.action)
        provider_id = (
            (agent.provider_id if agent else None) or project.default_provider_id
        )
        provider = db.get(Provider, provider_id) if provider_id else None
        provider = actions.effective_provider(agent, provider)

        budget = usage.budget_state(db, project)
        if project.budget_enforced and budget["over"]:
            schedule.last_run_at = _now()
            schedule.last_status = "skipped: budget"
            schedule.last_report = (
                f"monthly token budget reached ({budget['used']}/{budget['budget']})"
            )
            db.add(schedule)
            db.commit()
            db.refresh(schedule)
            await asyncio.to_thread(
                notify.send,
                f"Schedule skipped: {schedule.action}",
                f"{project.name}: {schedule.last_report}",
                "high",
                ["warning"],
                settings.notification_url(f"/p/{project.id}/automations"),
            )
            return as_dict(schedule)

        if not provider:
            schedule.last_run_at = _now()
            schedule.last_status = "error"
            schedule.last_report = "no provider configured for this project"
        else:
            payload = (event or {}).get("payload") or {}
            instruction = (
                schedule.instruction.replace("{date}", _now().date().isoformat())
                .replace("{event}", str((event or {}).get("kind", "")))
                .replace("{event_title}", str(payload.get("title", "")))
                .replace("{event_url}", str(payload.get("url", "")))
            )
            if event:
                if not instruction.strip():
                    instruction = (
                        f"React to this event: {event.get('kind')} "
                        f"({payload.get('title', '')})"
                    )
                schedule.last_event_key = event.get("key", "")
            digest = totem_store.digest(repos.memory_root(project), task=instruction)
            system = build_system_prompt(
                ProjectContext.from_project(project),
                agents_md=project.agents_md,
                memory_context=digest.get("context", ""),
                user_task=instruction,
                extra_context=settings.prompt_context(db),
            )
            if agent and agent.system_prompt:
                system += f"\n\n## Agent instructions\n{agent.system_prompt}"
            system += SCHEDULE_NOTE
            groups = actions.ACTIONS_BY_KEY.get(schedule.action, {}).get("tools", "")
            report, error, tokens = await run_once(
                project,
                provider,
                system,
                instruction or "Run the scheduled job.",
                groups=groups,
                tasks_db=db,
            )
            usage.record(
                db, project.id, action=schedule.action, model=provider.model, usage=tokens
            )
            schedule.last_status = "error" if error else "ok"
            schedule.last_report = (error or report or "").strip()[:4000]
            schedule.last_run_at = _now()

        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        status = schedule.last_status or "ok"
        await asyncio.to_thread(
            notify.send,
            f"Schedule {status}: {schedule.action}",
            f"{project.name}: {(schedule.last_report or '(no report)')[:300]}",
            "high" if status == "error" else "default",
            ["warning"] if status == "error" else ["white_check_mark"],
            settings.notification_url(f"/p/{project.id}/automations"),
        )
        return as_dict(schedule)


def _in_cooldown(schedule: Schedule) -> bool:
    if not schedule.cooldown_minutes or not schedule.last_run_at:
        return False
    last = _naive(schedule.last_run_at)
    return (_naive(_now()) - last) < timedelta(minutes=schedule.cooldown_minutes)


def _event_plan(db: Session) -> tuple[list[tuple[int, dict]], list[int]]:
    """Match unhandled events to event-triggered schedules."""
    plan: list[tuple[int, dict]] = []
    handle_ids: list[int] = []
    for event in events.unhandled(db):
        data = events.as_dict(event)
        for schedule in events.event_schedules(db, event.project_id):
            if events.matches(schedule, event) and not _in_cooldown(schedule):
                plan.append((schedule.id, data))
        handle_ids.append(event.id)
    return plan, handle_ids


def _poll_inbox() -> None:
    """In its own thread and session, so notify.send never blocks the loop."""
    with Session(engine()) as db:
        inbox.poll_all(db)


async def worker() -> None:
    """Tick forever: reminders, briefing, watches, schedules, then inbox."""
    inbox_clock = INBOX_POLL_SECONDS
    while True:
        try:
            with Session(engine()) as db:
                reminders.fire_due(db)
                await _maybe_send_briefing(db)
                await _maybe_send_daily_plan(db)
                await _maybe_send_weekly_review(db)
                await watchers.check_due(db)

            with Session(engine()) as db:
                due_ids = [s.id for s in due_schedules(db)]
            for schedule_id in due_ids:
                await run_schedule(schedule_id)

            with Session(engine()) as db:
                event_plan, handle_ids = _event_plan(db)
            for schedule_id, event in event_plan:
                await run_schedule(schedule_id, event=event)
            if handle_ids:
                with Session(engine()) as db:
                    for event_id in handle_ids:
                        row = db.get(Event, event_id)
                        if row is not None:
                            events.mark_handled(db, row)
                    db.commit()

            inbox_clock += TICK_SECONDS
            if inbox_clock >= INBOX_POLL_SECONDS:
                inbox_clock = 0
                await asyncio.to_thread(_poll_inbox)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
