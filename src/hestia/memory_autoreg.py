"""Best-effort implementation-memory registration after code writes.

Mirrors encoder's file-tool → memory integration without forcing a `memory`
argument on every tool: after a successful write/edit/apply_patch, upsert the
implementation memory for the changed path (totem dedupes by path).

Enabled when the project already uses Totem (`.totem` exists), or forced with
`HESTIA_MEMORY_AUTOREGISTER=1`; disabled with `=0`. Never raises: a memory
failure must not fail an edit.
"""

from __future__ import annotations

import os
from pathlib import Path

from hestia import totem_store


def _enabled(project_dir: Path) -> bool:
    flag = os.environ.get("HESTIA_MEMORY_AUTOREGISTER", "").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return False
    if flag in ("1", "true", "on", "yes"):
        return True
    return (project_dir / ".totem").exists()


def record(project_dir: Path | None, abs_path: Path, action: str = "modified") -> None:
    if project_dir is None:
        return
    try:
        if not _enabled(project_dir):
            return
        totem_store.register_write(
            project_dir,
            str(abs_path),
            f"{action} {abs_path.name}",
            action,
            ["implementation"],
        )
    except Exception:  # noqa: BLE001
        return
