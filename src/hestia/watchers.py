"""Watchers: page diff, feed new items, and LLM condition checks.

Checked by the worker on each watch's interval. Notifications only fire when
something actually happens; condition watches complete when met.
"""

from __future__ import annotations

import difflib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from hestia import actions, events, notify, repos, settings, totem_store, usage, webfetch
from hestia.agent.prompt import build_system_prompt
from hestia.agent.run import run_once
from hestia.registry.models import Project, Provider, Watch
from hestia.tools.registry import ProjectContext

KINDS = ["page", "feed", "condition"]
NOTIFY_ON = ["change", "appear"]
MIN_INTERVAL = 30
SNAPSHOT_LIMIT = 100_000

CONDITION_PROMPT = """\
You are checking a watch condition.

Condition: {condition}
URL: {url}

Fetch the URL (or use the repository and GitHub tools if they are more
relevant). Then reply with exactly one first line: MET or NOT_MET. Follow it
with one or two sentences of evidence. Do not do anything else.
"""


class InvalidWatch(ValueError):
    """Raised for invalid watch input; mapped to HTTP 400 / tool errors."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def as_dict(watch: Watch) -> dict:
    return {
        "id": watch.id,
        "project_id": watch.project_id,
        "kind": watch.kind,
        "url": watch.url,
        "condition": watch.condition,
        "interval_minutes": watch.interval_minutes,
        "status": watch.status,
        "notify_on": watch.notify_on,
        "last_result": watch.last_result,
        "last_checked_at": watch.last_checked_at.isoformat()
        if watch.last_checked_at
        else None,
        "created_at": watch.created_at.isoformat() if watch.created_at else None,
    }


def create(
    db: Session,
    kind: str,
    url: str | None = None,
    condition: str = "",
    interval_minutes: int = 60,
    notify_on: str = "change",
    project_id: int | None = None,
) -> Watch:
    kind = (kind or "page").strip().lower()
    if kind not in KINDS:
        raise InvalidWatch(f"kind must be one of: {', '.join(KINDS)}")
    url = (url or "").strip() or None
    condition = (condition or "").strip()
    if kind in ("page", "feed") and not url:
        raise InvalidWatch("url is required for page and feed watches")
    if kind == "condition" and not condition:
        raise InvalidWatch("condition is required for condition watches")
    notify_on = (notify_on or "change").strip().lower()
    if notify_on not in NOTIFY_ON:
        raise InvalidWatch(f"notify_on must be one of: {', '.join(NOTIFY_ON)}")
    try:
        interval = max(MIN_INTERVAL, int(interval_minutes))
    except (TypeError, ValueError):
        raise InvalidWatch("interval_minutes must be a number")
    watch = Watch(
        project_id=project_id,
        kind=kind,
        url=url,
        condition=condition,
        interval_minutes=interval,
        notify_on=notify_on,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    return watch


def list_all(db: Session) -> list[Watch]:
    return db.exec(select(Watch).order_by(Watch.id)).all()


def due(db: Session, now: datetime | None = None) -> list[Watch]:
    now = _naive(now or _utcnow())
    rows = db.exec(select(Watch).where(Watch.status == "active")).all()
    out = []
    for watch in rows:
        last = _naive(watch.last_checked_at) if watch.last_checked_at else None
        interval = timedelta(minutes=max(MIN_INTERVAL, watch.interval_minutes))
        if last is None or now - last >= interval:
            out.append(watch)
    return out


def update(db: Session, watch: Watch, fields: dict) -> Watch:
    if "status" in fields:
        status = (fields["status"] or "").strip().lower()
        if status not in ("active", "paused", "done"):
            raise InvalidWatch("status must be active, paused, or done")
        watch.status = status
    if "interval_minutes" in fields:
        try:
            watch.interval_minutes = max(MIN_INTERVAL, int(fields["interval_minutes"]))
        except (TypeError, ValueError):
            raise InvalidWatch("interval_minutes must be a number")
    if "condition" in fields:
        watch.condition = (fields["condition"] or "").strip()
    db.add(watch)
    db.commit()
    db.refresh(watch)
    return watch


def delete(db: Session, watch: Watch) -> None:
    db.delete(watch)
    db.commit()


def _project_for(db: Session, watch: Watch) -> Project | None:
    if watch.project_id:
        project = db.get(Project, watch.project_id)
        if project is not None:
            return project
    agent = actions.resolve_action(db, "chat")
    for project in db.exec(select(Project)).all():
        provider_id = (agent.provider_id if agent else None) or project.default_provider_id
        if provider_id and db.get(Provider, provider_id):
            return project
    return None


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in element:
        local = child.tag.split("}")[-1].lower()
        if local in names and child.text and child.text.strip():
            return child.text.strip()
    return ""


def _child_link(element: ET.Element) -> str:
    for child in element:
        local = child.tag.split("}")[-1].lower()
        if local == "link":
            href = child.get("href")
            if href:
                return href.strip()
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if tag not in ("item", "entry"):
            continue
        title = _child_text(element, {"title"}) or "(untitled)"
        link = _child_link(element)
        guid = _child_text(element, {"guid", "id"}) or link or title
        items.append({"id": guid, "title": title, "link": link})
    return items


def _diff_excerpt(old: str, new: str, limit: int = 40) -> str:
    diff = list(difflib.unified_diff(old.split(), new.split(), lineterm="", n=2))
    if not diff:
        return "(changed)"
    return " ".join(diff[2 : 2 + limit])[:500]


def _check_page(watch: Watch) -> None:
    result = webfetch.fetch(watch.url)
    text = " ".join(result["text"].split())[:SNAPSHOT_LIMIT]
    old = watch.snapshot or ""
    if not old:
        watch.snapshot = text
        watch.last_result = "baseline stored"
        return
    if watch.notify_on == "appear":
        needle = watch.condition.strip().lower()
        present = bool(needle) and needle in text.lower()
        appeared = present and needle not in old.lower()
        watch.last_result = "condition present" if present else "condition not present"
        if appeared:
            notify.send(
                f"Watch matched: {watch.condition}",
                f"{watch.url}\n\nCondition found on the page.",
                tags=["eyes"],
                url=watch.url,
            )
            watch.status = "done"
        watch.snapshot = text
        return
    if text != old:
        notify.send(
            "Page changed",
            f"{watch.url}\n\n{_diff_excerpt(old, text)}",
            tags=["eyes"],
            url=watch.url,
        )
        watch.last_result = "changed"
        watch.snapshot = text
    else:
        watch.last_result = "unchanged"


def _check_feed(watch: Watch) -> None:
    result = webfetch.fetch(watch.url)
    items = parse_feed(result["text"])
    if not items:
        watch.last_result = "no feed items found"
        return
    try:
        seen = list(json.loads(watch.snapshot).get("seen", []))
    except (ValueError, AttributeError):
        seen = []
    if not seen:
        watch.snapshot = json.dumps({"seen": [i["id"] for i in items][:500]})
        watch.last_result = f"baseline: {len(items)} items"
        return
    seen_set = set(seen)
    new_items = [i for i in items if i["id"] not in seen_set]
    if new_items:
        lines = "\n".join(f"- {i['title']} {i['link']}".strip() for i in new_items[:5])
        notify.send(
            f"{len(new_items)} new in feed",
            f"{watch.url}\n\n{lines}",
            tags=["newspaper"],
            url=new_items[0]["link"] or watch.url,
        )
        watch.last_result = f"{len(new_items)} new items"
        watch.snapshot = json.dumps(
            {"seen": ([i["id"] for i in new_items] + seen)[:500]}
        )
    else:
        watch.last_result = "no new items"


async def _check_condition(db: Session, watch: Watch) -> None:
    project = _project_for(db, watch)
    if project is None:
        watch.last_result = "no project with a provider; skipped"
        return
    agent = actions.resolve_action(db, "chat")
    provider_id = (agent.provider_id if agent else None) or project.default_provider_id
    provider = db.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent, provider)
    if provider is None:
        watch.last_result = "no provider configured; skipped"
        return
    digest = totem_store.digest(
        repos.memory_root(project), task=f"Check watch: {watch.condition}"
    )
    system = build_system_prompt(
        ProjectContext.from_project(project),
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task=f"Check watch: {watch.condition}",
        extra_context=settings.prompt_context(db),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + CONDITION_PROMPT.format(
        condition=watch.condition, url=watch.url or "(none)"
    )
    report, error, tokens = await run_once(
        project,
        provider,
        system,
        "Check the watch condition.",
        groups="web,repo,files,github",
        tasks_db=db,
    )
    usage.record(db, project.id, action="watch", model=provider.model, usage=tokens)
    if error:
        watch.last_result = f"error: {error[:200]}"
        return
    first = (report or "").strip().splitlines()[0] if (report or "").strip() else ""
    upper = first.upper()
    met = "MET" in upper and "NOT_MET" not in upper
    summary = (report or "").strip()[:400] or "no report"
    watch.last_result = summary
    if met:
        notify.send(
            f"Watch met: {watch.condition}",
            summary,
            tags=["eyes"],
            url=watch.url or settings.notification_url("/g/watches"),
        )
        watch.status = "done"


def _is_hit(watch: Watch) -> bool:
    result = watch.last_result or ""
    if watch.status == "done":
        return True
    if result == "changed":
        return True
    return result.endswith("new items") and not result.startswith("baseline")


async def check(db: Session, watch: Watch) -> Watch:
    watch.last_checked_at = _utcnow()
    try:
        if watch.kind == "page":
            _check_page(watch)
        elif watch.kind == "feed":
            _check_feed(watch)
        elif watch.kind == "condition":
            await _check_condition(db, watch)
    except Exception as e:  # network, parse, provider; record and keep going
        watch.last_result = f"error: {str(e)[:200]}"
    if watch.project_id and _is_hit(watch):
        events.emit(
            db,
            watch.project_id,
            "watch_hit",
            {
                "title": watch.condition or watch.url or f"watch {watch.id}",
                "url": watch.url,
                "text": watch.last_result or "",
            },
            key=f"watch:{watch.id}:{watch.last_checked_at.isoformat()}",
        )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    return watch


async def check_due(db: Session) -> int:
    checked = 0
    for watch in due(db):
        await check(db, watch)
        checked += 1
    return checked
