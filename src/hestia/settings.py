"""Global assistant settings + Totem-backed user memory.

Owner identity, standing instructions, and preferences live in the Totem user
DB (canonical memory); this module is a thin facade so the rest of the app and
the settings UI keep a simple key/value view. Everything else (timezone,
briefing config, ...) stays as registry Setting rows.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from hestia.registry.models import Setting

logger = logging.getLogger("hestia.settings")

DEFAULTS: dict[str, str] = {
    "user_name": "",
    "timezone": "UTC",
    "instructions": "",
    "preferences": "[]",
    "briefing_enabled": "0",
    "briefing_time": "08:00",
    "briefing_agent": "0",
    "briefing_last_sent": "",
    "daily_plan_enabled": "0",
    "daily_plan_time": "08:30",
    "daily_plan_last_sent": "",
    "weekly_review_enabled": "0",
    "weekly_review_day": "4",  # Monday=0 .. Sunday=6
    "weekly_review_time": "16:00",
    "weekly_review_last_sent": "",
    "web_fetch_enabled": "1",
    "browser_enabled": "1",
    "browser_cdp_url": "",
    "show_thinking": "1",
}

_USER_KEYS = ("user_name", "instructions", "preferences")
_MIGRATED = False

_TRUE = {"1", "true", "yes", "on"}


def as_bool(value: str | None, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in _TRUE


def _totem():
    from hestia import totem_store

    return totem_store


def _tagged(items: list[dict], *tags: str) -> list[dict]:
    wanted = set(tags)
    out = []
    for item in items:
        item_tags = {str(t).lower() for t in (item.get("tags") or [])}
        if item_tags & wanted:
            out.append(item)
    return out


def _created(item: dict) -> str:
    return str(item.get("createdAt") or item.get("created_at") or "")


def _raw_setting(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULTS.get(key, "")


def _clear_raw(db: Session) -> None:
    changed = False
    for key in _USER_KEYS:
        row = db.get(Setting, key)
        if row is not None and row.value not in ("", "[]", None):
            row.value = "[]" if key == "preferences" else ""
            db.add(row)
            changed = True
    if changed:
        db.commit()


def _ensure_migrated(db: Session) -> None:
    """Move legacy settings user data into Totem user memory once."""
    global _MIGRATED
    if _MIGRATED:
        return
    _MIGRATED = True
    try:
        ts = _totem()
        items = ts.user_list(limit=300)
        tags: set[str] = set()
        for item in items:
            tags |= {str(t).lower() for t in (item.get("tags") or [])}
        if "identity" not in tags:
            name = str(_raw_setting(db, "user_name") or "").strip()
            if name:
                ts.user_create(
                    type="observation",
                    title="Owner identity",
                    statement=name,
                    tags=["identity"],
                    metadata={"observation": "identity"},
                    asserted_by="user",
                    scope=USER_SCOPE,
                )
        if "standing-instruction" not in tags:
            instructions = str(_raw_setting(db, "instructions") or "").strip()
            if instructions:
                ts.user_create(
                    type="observation",
                    title="Standing instructions",
                    statement=instructions,
                    tags=["standing-instruction"],
                    metadata={"observation": "standing_instruction"},
                    asserted_by="user",
                    scope=USER_SCOPE,
                )
        if "preference" not in tags:
            try:
                prefs = json.loads(str(_raw_setting(db, "preferences") or "[]"))
            except ValueError:
                prefs = []
            for pref in prefs if isinstance(prefs, list) else []:
                text = str(pref).strip()
                if text:
                    ts.user_create(
                        type="observation",
                        title=f"Preference: {text[:60]}",
                        statement=text,
                        tags=["preference"],
                        metadata={"observation": "preference"},
                        asserted_by="user",
                        scope=USER_SCOPE,
                    )
        _clear_raw(db)
    except Exception:
        logger.exception("user memory migration failed")


USER_SCOPE = '{"kind": "user", "value": "global"}'


def _replace_tagged(ts, tags: list[str], title: str, text: str, observation: str) -> None:
    for item in _tagged(ts.user_list(limit=300), *tags):
        ts.user_delete(item["id"], "updated by owner")
    if text:
        ts.user_create(
            type="observation",
            title=title,
            statement=text,
            tags=list(tags),
            metadata={"observation": observation},
            asserted_by="user",
            scope=USER_SCOPE,
        )


def _replace_preferences(ts, texts: list[str]) -> None:
    for item in _tagged(ts.user_list(limit=300), "preference"):
        ts.user_delete(item["id"], "updated by owner")
    for text in texts:
        ts.user_create(
            type="observation",
            title=f"Preference: {text[:60]}",
            statement=text,
            tags=["preference"],
            metadata={"observation": "preference"},
            asserted_by="user",
            scope=USER_SCOPE,
        )


def get_all(db: Session) -> dict[str, str]:
    _ensure_migrated(db)
    values = dict(DEFAULTS)
    for row in db.exec(select(Setting)).all():
        values[row.key] = row.value
    try:
        items = _totem().user_list(limit=300)
        identity = _tagged(items, "identity")
        if identity:
            values["user_name"] = identity[0].get("statement") or ""
        standing = _tagged(items, "standing-instruction")
        if standing:
            values["instructions"] = standing[0].get("statement") or ""
        prefs = sorted(_tagged(items, "preference"), key=_created)
        values["preferences"] = json.dumps(
            [p.get("statement", "") for p in prefs if p.get("statement")]
        )
    except Exception:
        logger.exception("could not read user memory")
    return values


def get(db: Session, key: str, default: str | None = None) -> str:
    if key in _USER_KEYS:
        return get_all(db).get(key, DEFAULTS.get(key, ""))
    row = db.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, default if default is not None else "")


def get_bool(db: Session, key: str, default: bool = False) -> bool:
    return as_bool(get(db, key, "1" if default else "0"), default)


def set_many(db: Session, values: dict) -> dict[str, str]:
    _ensure_migrated(db)
    ts = _totem()
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if key == "user_name":
            _replace_tagged(
                ts, ["identity"], "Owner identity", str(value or "").strip(), "identity"
            )
        elif key == "instructions":
            _replace_tagged(
                ts,
                ["standing-instruction"],
                "Standing instructions",
                str(value or "").strip(),
                "standing_instruction",
            )
        elif key == "preferences":
            raw = value
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = [raw] if raw else []
            texts = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []
            _replace_preferences(ts, texts)
        else:
            row = db.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=str(value))
            else:
                row.value = str(value)
                row.updated_at = datetime.now(timezone.utc)
            db.add(row)
    db.commit()
    return get_all(db)


def preferences(db: Session) -> list[str]:
    """Global standing preferences: durable rules injected into every prompt."""
    _ensure_migrated(db)
    try:
        items = sorted(_tagged(_totem().user_list(limit=300), "preference"), key=_created)
    except Exception:
        logger.exception("could not read preferences")
        return []
    return [str(i.get("statement", "")).strip() for i in items if i.get("statement")]


def add_preference(db: Session, text: str) -> list[str]:
    text = (text or "").strip()
    if text and text not in preferences(db):
        _totem().user_create(
            type="observation",
            title=f"Preference: {text[:60]}",
            statement=text,
            tags=["preference"],
            metadata={"observation": "preference"},
            asserted_by="user",
            scope=USER_SCOPE,
        )
    return preferences(db)


def set_preference(db: Session, index: int, text: str) -> list[str]:
    text = (text or "").strip()
    items = sorted(_tagged(_totem().user_list(limit=300), "preference"), key=_created)
    if 0 <= index < len(items) and text:
        _totem().user_update(
            items[index]["id"],
            title=f"Preference: {text[:60]}",
            statement=text,
            reason="edited by owner",
        )
    return preferences(db)


def remove_preference(db: Session, index: int) -> list[str]:
    items = sorted(_tagged(_totem().user_list(limit=300), "preference"), key=_created)
    if 0 <= index < len(items):
        _totem().user_delete(items[index]["id"], "removed by owner")
    return preferences(db)


def timezone_name(db: Session) -> str:
    return get(db, "timezone", "UTC") or "UTC"


def local_now(db: Session) -> datetime:
    try:
        tz = ZoneInfo(timezone_name(db))
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    return datetime.now(timezone.utc).astimezone(tz)


def origin() -> str | None:
    return (os.environ.get("HESTIA_ORIGIN") or "").rstrip("/") or None


def notification_url(path: str) -> str | None:
    base = origin()
    return f"{base}/#{path}" if base else None


def prompt_context(db: Session) -> str:
    """Clock context. Owner identity/preferences come from Totem user memory."""
    now_utc = datetime.now(timezone.utc)
    local = local_now(db)
    return (
        f"Current time: {now_utc.isoformat(timespec='seconds')} UTC "
        f"(local {local.isoformat(timespec='minutes')}, {timezone_name(db)})."
    )
