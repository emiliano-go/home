"""Synthetic per-turn reminders appended to the last user message.

Mirrors encoder's `session/reminders.ts`: short notes that must be close to the
end of the prompt (where attention is strongest) rather than buried in the
system prompt. Nothing is persisted; applying twice is idempotent.
"""

from __future__ import annotations

MARKER = "<system-reminder>"
PLAN_REMINDER = (
    "Plan mode is enforced: call plan_read before each step and plan_update with the step "
    "status after it; the next write is blocked until the drift check is recorded."
)
DECISION_REMINDER = (
    "A decision engine will evaluate this turn; make the minimal correct change, run the "
    "relevant checks, and report results before finishing."
)


def apply(messages: list[dict], *, plan_mode: bool = False, decision: bool = False) -> list[dict]:
    notes = []
    if plan_mode:
        notes.append(PLAN_REMINDER)
    if decision:
        notes.append(DECISION_REMINDER)
    if not notes:
        return messages

    text = "\n".join([MARKER, *notes, "</system-reminder>"])
    out = [dict(message) for message in messages]
    for message in reversed(out):
        if message.get("role") != "user":
            continue
        content = message.get("content") or ""
        if MARKER in content:  # already reminded
            return out
        message["content"] = f"{content}\n\n{text}" if content else text
        break
    return out
