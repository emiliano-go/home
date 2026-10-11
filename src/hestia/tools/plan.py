"""Plan-first workflow: plan artifacts and the per-step drift-check gate."""

from __future__ import annotations

import re
from pathlib import Path

from hestia.tools.registry import ProjectContext, Registry, Tool, schema

GATED_TOOLS = {
    "write_file",
    "git_create_branch",
    "git_commit",
    "git_push",
    "gh_open_pr",
    "gh_merge_pr",
}

PLAN_REL = Path("plans") / "current.md"
_DRIFT_HEADER = "## Drift log"
_STATUS_MARK = {"done": "x", "in_progress": "~", "blocked": "!", "skipped": "-"}


def plan_path(ctx: ProjectContext) -> Path:
    if ctx.workspace_path is None:
        raise ValueError("project has no workspace")
    return Path(ctx.workspace_path) / PLAN_REL


def _gate_active(ctx: ProjectContext, registry: Registry | None = None) -> bool:
    """Only the principal run is gated: plan tools must be in its registry."""
    if not ctx.require_plan:
        return False
    if registry is not None and registry.get("plan_update") is None:
        return False
    return True


def check_gate(
    ctx: ProjectContext, tool_name: str, registry: Registry | None = None
) -> str | None:
    """Why this write is blocked, or None when it may proceed."""
    if not _gate_active(ctx, registry) or tool_name not in GATED_TOOLS:
        return None
    if not plan_path(ctx).exists():
        return (
            "blocked: this project requires a plan before code changes. Call "
            "plan_write with a short summary and the ordered steps first, then retry."
        )
    if ctx.plan_check_pending:
        return (
            "blocked: this project requires a drift check after each step. Call "
            "plan_update with the step number, status (done/in_progress/blocked/"
            "skipped) and drift notes, then retry this write."
        )
    return None


def after_write(
    ctx: ProjectContext, tool_name: str, ok: bool, registry: Registry | None = None
) -> None:
    if ok and _gate_active(ctx, registry) and tool_name in GATED_TOOLS:
        ctx.plan_check_pending = True


def _write_plan(ctx: ProjectContext, summary: str, steps: list) -> dict:
    lines = ["# Plan", "", str(summary).strip(), "", "## Steps"]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. [ ] {str(step).strip()}")
    path = plan_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.plan_check_pending = False
    return {"path": str(PLAN_REL), "steps": len(steps)}


def _update_plan(ctx: ProjectContext, step: int, status: str, notes: str) -> dict:
    if status not in _STATUS_MARK:
        raise ValueError(f"unknown status '{status}'; use {', '.join(_STATUS_MARK)}")
    path = plan_path(ctx)
    if not path.exists():
        raise ValueError("no plan yet: call plan_write first")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{step}\.\s*\[.\]", re.M)
    if not pattern.search(text):
        raise ValueError(
            f"step {step} not found in the plan; call plan_read to see the steps"
        )
    text = pattern.sub(f"{step}. [{_STATUS_MARK[status]}]", text, count=1)
    entry = f"- step {step} {status}: {notes.strip()}" if notes.strip() else f"- step {step} {status}"
    if _DRIFT_HEADER in text:
        text = text.rstrip() + "\n" + entry + "\n"
    else:
        text = text.rstrip() + f"\n\n{_DRIFT_HEADER}\n{entry}\n"
    path.write_text(text, encoding="utf-8")
    ctx.plan_check_pending = False
    return {"path": str(PLAN_REL), "step": step, "status": status}


def _read_plan(ctx: ProjectContext, args: dict | None = None) -> dict:
    path = plan_path(ctx)
    if not path.exists():
        return {"path": str(PLAN_REL), "content": "", "exists": False}
    return {"path": str(PLAN_REL), "content": path.read_text(encoding="utf-8"), "exists": True}


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="plan_write",
        description=(
            "Write or replace the implementation plan for this project in the "
            "workspace (plans/current.md) before making code changes. Pass a "
            "short summary and the ordered steps."
        ),
        parameters=schema({
            "summary": {"type": "string", "description": "what the work is and why"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ordered implementation steps",
            },
        }, ["summary", "steps"]),
        handler=lambda ctx, a: _write_plan(ctx, a["summary"], a["steps"]),
        group="plan",
        effect="write",
    ))
    registry.register(Tool(
        name="plan_update",
        description=(
            "Record a step's status and any drift from the plan (required after "
            "each code-changing step when the project requires a plan)."
        ),
        parameters=schema({
            "step": {"type": "integer", "description": "1-based step number from plan_read"},
            "status": {
                "type": "string",
                "enum": ["done", "in_progress", "blocked", "skipped"],
            },
            "notes": {"type": "string", "description": "what changed vs the plan, or why"},
        }, ["step", "status"]),
        handler=lambda ctx, a: _update_plan(
            ctx, int(a["step"]), a["status"], a.get("notes") or ""
        ),
        group="plan",
        effect="write",
    ))
    registry.register(Tool(
        name="plan_read",
        description="Read the current implementation plan and its drift log.",
        parameters=schema({}, []),
        handler=_read_plan,
        group="plan",
    ))
