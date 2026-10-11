"""Strict decision state and normalization, ported from encoder.

The state is what the judge sees: task, memory, answer, tool calls, changes
(diffs), grounding. `normalize_state` applies the same caps as encoder so the
Laya token budget and captured-state format match.
"""

from __future__ import annotations

from typing import Any

MAX_DIFF_PER_HUNK = 4096
MAX_DIFF_TOTAL = 16_384
MUTATING_TOOLS = {"edit", "apply_patch", "write", "bash"}


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "…[truncated]"


def _task_relevant(task: str, path: str | None) -> bool:
    if not path:
        return False
    lowered = task.lower()
    return any(part and part in lowered for part in path.lower().replace("\\", "/").split("/"))


def _budget_diffs(changes: list[dict], task: str) -> list[dict]:
    budgeted: dict[int, str] = {}
    remaining = MAX_DIFF_TOTAL
    order = sorted(
        range(len(changes)),
        key=lambda i: (_task_relevant(task, changes[i].get("path")), i),
        reverse=True,
    )
    for index in order:
        diff = changes[index].get("diff")
        if not isinstance(diff, str) or not diff or remaining <= 0:
            continue
        take = min(len(diff), MAX_DIFF_PER_HUNK, remaining)
        budgeted[index] = diff[:take]
        remaining -= take
    return [
        {**{key: value for key, value in change.items() if key != "diff"}, **({"diff": budgeted[index]} if index in budgeted else {})}
        for index, change in enumerate(changes)
    ]


def normalize_state(state: dict) -> dict:
    """Apply encoder's caps. `memory` leads so the judge's head-slice keeps it."""
    task = state.get("task") or ""
    memory = state.get("memory")
    answer = state.get("answer")
    grounding = state.get("grounding")
    return {
        "task": truncate(task, 600),
        "memory": [
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "title": truncate(item.get("title") or "", 80),
                "statement": truncate(item.get("statement") or "", 160),
            }
            for item in (memory or [])[:2]
        ],
        "answer": None if answer is None else truncate(str(answer), 2000),
        "toolCalls": (state.get("toolCalls") or [])[:20],
        "changes": _budget_diffs(list(state.get("changes") or []), task),
        "grounding": [
            {**entry, "output": truncate(str(entry.get("output") or ""), 2000)}
            for entry in (grounding or [])[:5]
        ],
    }


def build_state(
    *,
    task: str,
    assistant_text: str | None,
    tool_calls: list[dict] | None,
    mutations: list[dict],
    grounding: list[dict] | None,
    memory: list[dict] | None,
) -> dict:
    """Assemble the state from a completed agent turn.

    `mutations` are `{tool, input, output, paths?, diff?}`; the patch (diff) goes
    in `input` to match the retrained judge. Evidence is deliberately omitted
    (the verify lane owns execution); memory is derived by the caller.
    """
    changes = [
        {
            "tool": mutation.get("tool"),
            "input": mutation.get("diff") or mutation.get("input") or "",
            "output": mutation.get("output") or "",
            **({"path": mutation["paths"][0]} if mutation.get("paths") else {}),
        }
        for mutation in mutations
    ]
    return {
        "task": task,
        "memory": memory or [],
        "answer": assistant_text,
        "toolCalls": tool_calls or [],
        "changes": changes,
        "grounding": grounding or [],
    }
