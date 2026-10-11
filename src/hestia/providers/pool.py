"""API-key pools and rotation, ported from encoder.

A provider can hold several keys (``Provider.keys`` JSON list) plus a rotation
state (``Provider.key_state``): keys that hit 429/402 are suspended until their
cooldown elapses; 401/403 keys are revoked. ``active()`` returns the first
usable key. State is persisted on the provider row by the caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

DEFAULT_COOLDOWN = 60
MAX_COOLDOWN = 3600


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def keys_of(provider) -> list[str]:
    """All usable-looking keys: stored list, the single stored key, and the env var."""
    keys: list[str] = []
    raw = getattr(provider, "keys", "") or ""
    try:
        parsed = json.loads(raw) if raw else []
        keys = [str(k).strip() for k in parsed if str(k).strip()]
    except ValueError:
        keys = []
    stored = getattr(provider, "api_key", None)
    if stored and stored not in keys:
        keys.insert(0, stored)
    env = getattr(provider, "api_key_env", "") or ""
    if env and os.environ.get(env) and os.environ[env] not in keys:
        keys.append(os.environ[env])
    return keys


def _state(provider) -> dict:
    raw = getattr(provider, "key_state", "") or ""
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    if not isinstance(state, dict):
        state = {}
    return {"suspended": state.get("suspended", {}), "revoked": list(state.get("revoked", []))}


def active(provider, now: float | None = None) -> str | None:
    keys = keys_of(provider)
    if not keys:
        return None
    now = now or time.time()
    state = _state(provider)
    revoked = set(state["revoked"])
    suspended = state["suspended"]
    for key in keys:
        digest = hash_key(key)
        if digest in revoked:
            continue
        until = suspended.get(digest)
        if until and float(until) > now:
            continue
        return key
    return keys[0]  # everything unusable: return the first so the error surfaces


def should_rotate(status: int) -> str | None:
    if status in (429, 402):
        return "suspend"
    if status in (401, 403):
        return "revoke"
    return None


def cooldown_seconds(headers) -> int:
    retry = None
    if headers is not None:
        retry = headers.get("retry-after")
    try:
        return min(max(int(retry), 1), MAX_COOLDOWN)
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN


def note_failure(provider, key: str, status: int, cooldown: int = DEFAULT_COOLDOWN) -> None:
    """Record a failed key on the provider row (caller persists it)."""
    action = should_rotate(status)
    if action is None:
        return
    now = time.time()
    state = _state(provider)
    digest = hash_key(key)
    if action == "revoke":
        if digest not in state["revoked"]:
            state["revoked"].append(digest)
    else:
        state["suspended"][digest] = now + max(1, min(int(cooldown), MAX_COOLDOWN))
    provider.key_state = json.dumps(state)
