"""Context compaction: bound provider history without an LLM call.

Two deterministic passes, cheap enough to run on every turn:

- prune old tool outputs (they dominate history) to a short placeholder, keeping
  the most recent ones intact;
- if still over budget, keep the system prompt, the first user message, and the
  most recent tail that fits, dropping the middle. The tail is trimmed to a
  valid boundary so an assistant ``tool_calls`` message is never separated from
  its tool results.

No summary is generated; nothing is persisted, so recompaction is idempotent.
"""

from __future__ import annotations

import json

TOOL_PLACEHOLDER = "[older tool output pruned to keep context small]"
DEFAULT_BUDGET_TOKENS = 24_000
DEFAULT_KEEP_TOOLS = 8


def _text(message: dict) -> str:
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    if message.get("tool_calls"):
        text += " " + json.dumps(message["tool_calls"], default=str)
    return text


def estimate_tokens(messages: list[dict]) -> int:
    return sum(len(_text(m)) // 4 + 8 for m in messages)


def prune_tool_outputs(messages: list[dict], keep_recent: int = DEFAULT_KEEP_TOOLS) -> bool:
    """Blank the content of all but the most recent ``keep_recent`` tool results."""
    tool_indexes = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    stale = tool_indexes[:-keep_recent] if keep_recent else tool_indexes
    changed = False
    for i in stale:
        if messages[i].get("content") != TOOL_PLACEHOLDER:
            messages[i] = {**messages[i], "content": TOOL_PLACEHOLDER}
            changed = True
    return changed


def compact(
    messages: list[dict],
    token_budget: int = DEFAULT_BUDGET_TOKENS,
    keep_recent_tools: int = DEFAULT_KEEP_TOOLS,
) -> tuple[list[dict], bool]:
    """Return a compacted copy of ``messages`` and whether anything changed."""
    working = [dict(m) for m in messages]
    changed = prune_tool_outputs(working, keep_recent_tools)
    if estimate_tokens(working) <= token_budget:
        return working, changed

    head = working[:2]  # system prompt + first user message
    remaining = token_budget - estimate_tokens(head)
    tail: list[dict] = []
    for message in reversed(working[2:]):
        if estimate_tokens([message]) + estimate_tokens(tail) > remaining:
            break
        tail.insert(0, message)
    # never start a tail with orphaned tool results
    while tail and tail[0].get("role") == "tool":
        tail.pop(0)
    return head + tail, True
