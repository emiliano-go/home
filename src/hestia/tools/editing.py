"""Code-editing tools: ``edit``, ``apply_patch``, and ``bash``.

Gated by the project's write grade (`ProjectContext.write_mode`):

- ``read``  — not registered at all.
- ``ask``   — every call needs a fresh approved request (`ask_approval`).
- ``auto``  — file edits and shell commands run without a per-call prompt.
- ``yolo``  — same as auto; reserved for running against a throwaway sandbox.

Paths are sandboxed to the clone; ``.git``/``.totem`` are off limits. Bash runs
with the clone as cwd and a hard timeout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hestia import memory_autoreg
from hestia.tools.registry import ProjectContext, Registry, Tool, schema, write_allowed

_MAX_OUTPUT = 20_000
_BASH_TIMEOUT = 120
_GRADES = ("read", "ask", "auto", "yolo")


def _resolve(ctx: ProjectContext, rel: str, repo: str | None = None) -> Path:
    root = ctx.repo_path(repo).resolve()
    path = (root / rel).resolve()
    if path != root and not str(path).startswith(str(root) + os.sep):
        raise PermissionError(f"path escapes the repository: {rel}")
    parts = path.relative_to(root).parts
    if ".git" in parts or ".totem" in parts or ".hestia" in parts:
        raise PermissionError("refusing to touch Hestia's metadata (.git, .totem, .hestia)")
    return path


def _grade(ctx: ProjectContext) -> str:
    mode = (ctx.write_mode or "read").lower()
    return mode if mode in _GRADES else "read"


def _gate(ctx: ProjectContext, db, action: str) -> None:
    grade = _grade(ctx)
    if grade == "read":
        raise PermissionError("writes are disabled for this project (write mode: read)")
    if grade == "ask":
        if db is None:
            raise PermissionError("write mode 'ask' needs an approval, but no database session is available")
        from hestia.tools.gitwrites import _require_approval

        _require_approval(db, ctx, action)


def _replace(text: str, old: str, new: str, replace_all: bool) -> tuple[str, int]:
    count = text.count(old)
    if count == 0:
        raise ValueError("old_string was not found in the file")
    if count > 1 and not replace_all:
        raise ValueError(f"old_string appears {count} times; add more context or replace_all")
    return (text.replace(old, new) if replace_all else text.replace(old, new, 1)), (count if replace_all else 1)


def _edit(ctx: ProjectContext, args: dict, db) -> dict:
    rel = (args.get("path") or "").strip()
    old = args.get("old_string") or ""
    new = args.get("new_string")
    if not rel or not old:
        raise ValueError("path and old_string are required")
    if new is None:
        raise ValueError("new_string is required (use an empty string to delete)")
    if not write_allowed(ctx, rel):
        raise PermissionError(f"write scope: {rel} is outside the allowed files {ctx.write_allowlist}")
    _gate(ctx, db, "edit")
    path = _resolve(ctx, rel, args.get("repo"))
    if not path.is_file():
        raise FileNotFoundError(rel)
    updated, replacements = _replace(path.read_text(encoding="utf-8"), old, new, bool(args.get("replace_all")))
    path.write_text(updated, encoding="utf-8")
    memory_autoreg.record(ctx.memory_path, path, "edited")
    return {"path": rel, "replacements": replacements}


def _apply_patch(ctx: ProjectContext, args: dict, db) -> dict:
    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must be a non-empty list of {path, old_string, new_string}")
    _gate(ctx, db, "apply_patch")
    # Validate every edit before writing any: an apply_patch is all-or-nothing.
    staged: list[tuple[Path, str]] = []
    for entry in edits:
        rel = (entry.get("path") or "").strip()
        old = entry.get("old_string") or ""
        new = entry.get("new_string")
        if not rel or not old or new is None:
            raise ValueError("each edit needs path, old_string, and new_string")
        if not write_allowed(ctx, rel):
            raise PermissionError(f"write scope: {rel} is outside the allowed files {ctx.write_allowlist}")
        path = _resolve(ctx, rel, args.get("repo"))
        if not path.is_file():
            raise FileNotFoundError(rel)
        updated, _ = _replace(path.read_text(encoding="utf-8"), old, new, bool(entry.get("replace_all")))
        staged.append((path, updated))
    for path, updated in staged:
        path.write_text(updated, encoding="utf-8")
        memory_autoreg.record(ctx.memory_path, path, "patched")
    return {"edits": [path.name for path, _ in staged], "count": len(staged)}


def _bash(ctx: ProjectContext, args: dict, db) -> dict:
    command = (args.get("command") or "").strip()
    if not command:
        raise ValueError("command is required")
    _gate(ctx, db, "bash")
    cwd = ctx.repo_path(args.get("repo"))
    timeout = int(args.get("timeout") or _BASH_TIMEOUT)
    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=min(max(timeout, 1), 600),
        )
        code = proc.returncode
        output = f"{proc.stdout}\n{proc.stderr}".strip()
    except subprocess.TimeoutExpired:
        return {"code": 124, "output": f"command timed out after {timeout}s", "timed_out": True}
    return {"code": code, "output": output[-_MAX_OUTPUT:]}


def register(registry: Registry, db=None) -> None:
    registry.register(Tool(
        name="edit",
        description=(
            "Replace an exact string in a repository file (old_string must match "
            "exactly and uniquely unless replace_all is set). Prefer this over "
            "write_file for targeted changes."
        ),
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "path": {"type": "string", "description": "path relative to the repo root"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        }, ["path", "old_string", "new_string"]),
        handler=lambda ctx, a: _edit(ctx, a, db),
        group="writes",
        effect="write",
    ))
    registry.register(Tool(
        name="apply_patch",
        description=(
            "Apply several {path, old_string, new_string} edits atomically; if any "
            "edit fails to match, nothing is written."
        ),
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        }, ["edits"]),
        handler=lambda ctx, a: _apply_patch(ctx, a, db),
        group="writes",
        effect="write",
    ))
    registry.register(Tool(
        name="bash",
        description=(
            "Run a shell command in the repository clone (cwd = repo root) and "
            "return its exit code and output. Use for tests, builds, and git."
        ),
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "seconds (default 120, max 600)"},
        }, ["command"]),
        handler=lambda ctx, a: _bash(ctx, a, db),
        group="writes",
        effect="write",
        delegable=False,
    ))
