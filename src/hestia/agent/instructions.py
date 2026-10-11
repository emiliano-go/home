"""AGENTS.md / instruction hierarchy.

Collects agent instructions from, in order: a global ``AGENTS.md`` in the data
dir, extra files/globs from ``HESTIA_INSTRUCTIONS``, the repository root
(``AGENTS.md`` / ``CLAUDE.md``), and nested ``AGENTS.md`` files. Falls back to
the project's snapshotted ``AGENTS.md`` when none are found. Output is capped.
"""

from __future__ import annotations

import os
from glob import glob as _glob
from pathlib import Path

ROOT_FILES = ("AGENTS.md", "CLAUDE.md")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".totem", ".hestia", "dist", "build"}
MAX_NESTED = 12
MAX_CHARS = 12_000


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _extra_specs() -> list[str]:
    raw = os.environ.get("HESTIA_INSTRUCTIONS", "")
    return [part.strip() for part in raw.replace(os.pathsep, ",").split(",") if part.strip()]


def _nested(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("AGENTS.md")):
        rel = path.relative_to(root)
        if len(rel.parts) > 1 and not any(part in SKIP_DIRS for part in rel.parts):
            found.append(path)
        if len(found) >= MAX_NESTED:
            break
    return found


def load(root: Path | None, fallback: str | None = None) -> str:
    sections: list[str] = []

    from hestia import config

    global_md = _read(config.data_dir() / "AGENTS.md")
    if global_md:
        sections.append(global_md)

    for spec in _extra_specs():
        for match in _glob(spec):
            text = _read(Path(match))
            if text:
                sections.append(text)

    if root is not None:
        for name in ROOT_FILES:
            text = _read(root / name)
            if text:
                sections.append(text)
        for path in _nested(root):
            text = _read(path)
            if text:
                sections.append(f"# Nested instructions ({path.relative_to(root)})\n{text}")

    if not sections and fallback:
        sections.append(fallback.strip())

    joined = "\n\n".join(section for section in sections if section)
    return joined[:MAX_CHARS]
