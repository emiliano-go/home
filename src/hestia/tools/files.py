"""Read-only file tools, sandboxed to a project repository root.

Tools take an optional ``repo`` alias; the primary repository is the default.
"""

import fnmatch
import os
import re
from pathlib import Path

from hestia.tools.registry import ProjectContext, Registry, Tool, schema

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".totem", "dist", "build", ".mypy_cache", ".pytest_cache"}
_MAX_BYTES = 100_000


def _resolve(ctx: ProjectContext, rel: str, repo: str | None = None) -> Path:
    root = ctx.repo_path(repo).resolve()
    path = (root / rel).resolve()
    if not str(path).startswith(str(root) + os.sep) and path != root:
        raise PermissionError(f"path escapes project root: {rel}")
    return path


def _list_files(ctx: ProjectContext, pattern: str, limit: int = 200, repo: str | None = None) -> list[str]:
    root = ctx.repo_path(repo)
    matches = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            rel = str((Path(dirpath) / f).relative_to(root))
            glob = pattern.replace("**/", "*")
            if fnmatch.fnmatch(rel, glob):
                matches.append(rel)
                if len(matches) >= limit:
                    return matches
    return matches


def _read_file(ctx: ProjectContext, rel: str, repo: str | None = None) -> dict:
    path = _resolve(ctx, rel, repo)
    if not path.is_file():
        raise FileNotFoundError(rel)
    data = path.read_bytes()[:_MAX_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": rel, "binary": True, "size": path.stat().st_size}
    truncated = path.stat().st_size > _MAX_BYTES
    return {"path": rel, "content": text, "truncated": truncated}


def _grep(ctx: ProjectContext, pattern: str, path: str | None, limit: int, repo: str | None = None) -> list[dict]:
    rx = re.compile(pattern)
    files = [path] if path else _list_files(ctx, "*", limit=1000, repo=repo)
    out = []
    for rel in files:
        try:
            content = _read_file(ctx, rel, repo).get("content", "")
        except (FileNotFoundError, PermissionError):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if rx.search(line):
                out.append({"path": rel, "line": i, "text": line[:500]})
                if len(out) >= limit:
                    return out
    return out


def _repo_arg(description: str = "repo alias") -> dict:
    return {"type": "string", "description": description}


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="list_files",
        description="List repository files matching a glob (default '*'), e.g. 'src/**/*.py'.",
        parameters=schema({
            "repo": _repo_arg(),
            "pattern": {"type": "string"},
            "limit": {"type": "integer"},
        }, []),
        handler=lambda ctx, a: _list_files(ctx, a.get("pattern", "*"), a.get("limit", 200), a.get("repo")),
        group="files",
    ))
    registry.register(Tool(
        name="read_file",
        description="Read a UTF-8 text file inside a repository (max 100 KB returned).",
        parameters=schema({"repo": _repo_arg(), "path": {"type": "string"}}, ["path"]),
        handler=lambda ctx, a: _read_file(ctx, a["path"], a.get("repo")),
        group="files",
    ))
    registry.register(Tool(
        name="grep",
        description="Regex search over repository files, returns matching lines.",
        parameters=schema({
            "repo": _repo_arg(),
            "pattern": {"type": "string", "description": "Python regex"},
            "path": {"type": "string", "description": "optional single file to search"},
            "limit": {"type": "integer"},
        }, ["pattern"]),
        handler=lambda ctx, a: _grep(ctx, a["pattern"], a.get("path"), a.get("limit", 50), a.get("repo")),
        group="files",
    ))
    registry.register(Tool(
        name="read_agents_md",
        description="Read a repository's AGENTS.md (or equivalent agent instructions) if present.",
        parameters=schema({"repo": _repo_arg()}, []),
        handler=lambda ctx, a: _read_file(ctx, "AGENTS.md", a.get("repo"))
            if (ctx.repo_path(a.get("repo")) / "AGENTS.md").exists()
            else {"found": False},
        group="files",
    ))
    registry.register(Tool(
        name="list_docs",
        description="List documentation files (*.md) at a repo root and docs/ directory.",
        parameters=schema({"repo": _repo_arg()}, []),
        handler=lambda ctx, a: sorted(
            f for f in _list_files(ctx, "**/*.md", limit=100, repo=a.get("repo"))
            if f.count(os.sep) <= 1 or f.startswith("docs" + os.sep)
        ),
        group="files",
    ))
