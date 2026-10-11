"""Workspace tools: agent-generated files (plans, specs, notes).

The workspace is a per-project directory in the data volume, OUTSIDE the
repository clone. Agents may write here even though project code is
read-only; that is where plans, specs, and research notes live.
"""

import fnmatch
import os
from pathlib import Path

from hestia.tools.registry import ProjectContext, Registry, Tool, schema, write_allowed

_MAX_BYTES = 100_000


def _root(ctx: ProjectContext) -> Path:
    if ctx.workspace_path is None:
        raise ValueError("project has no workspace")
    ctx.workspace_path.mkdir(parents=True, exist_ok=True)
    return ctx.workspace_path.resolve()


def _resolve(ctx: ProjectContext, rel: str) -> Path:
    root = _root(ctx)
    path = (root / rel).resolve()
    if not str(path).startswith(str(root) + os.sep) and path != root:
        raise PermissionError(f"path escapes workspace: {rel}")
    return path


def _list(ctx: ProjectContext, pattern: str, limit: int = 200) -> list[str]:
    root = _root(ctx)
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            rel = str((Path(dirpath) / f).relative_to(root))
            if fnmatch.fnmatch(rel, pattern.replace("**/", "*")):
                out.append(rel)
                if len(out) >= limit:
                    return out
    return out


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="workspace_write",
        description=(
            "Write a file in the project workspace (persistent volume, outside "
            "the repository). Use for plans, specs, research notes, and any "
            "deliverable the user asks to save. Overwrites existing files."
        ),
        parameters=schema({
            "path": {"type": "string", "description": "relative path, e.g. plans/auth.md"},
            "content": {"type": "string"},
        }, ["path", "content"]),
        handler=lambda ctx, a: _write(ctx, a["path"], a["content"]),
        group="workspace",
        effect="write",
    ))
    registry.register(Tool(
        name="workspace_read",
        description="Read a file from the project workspace.",
        parameters=schema({"path": {"type": "string"}}, ["path"]),
        handler=lambda ctx, a: _read(ctx, a["path"]),
        group="workspace",
    ))
    registry.register(Tool(
        name="workspace_list",
        description="List workspace files matching a glob (default '*').",
        parameters=schema({"pattern": {"type": "string"}}, []),
        handler=lambda ctx, a: _list(ctx, a.get("pattern", "*")),
        group="workspace",
    ))


def _write(ctx: ProjectContext, rel: str, content: str) -> dict:
    if not write_allowed(ctx, rel):
        raise PermissionError(
            f"write scope: {rel} is outside the allowed files {ctx.write_allowlist}"
        )
    path = _resolve(ctx, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"path": rel, "bytes": len(content.encode())}


def _read(ctx: ProjectContext, rel: str) -> dict:
    path = _resolve(ctx, rel)
    if not path.is_file():
        raise FileNotFoundError(rel)
    data = path.read_bytes()[:_MAX_BYTES]
    return {"path": rel, "content": data.decode("utf-8", "replace")}
