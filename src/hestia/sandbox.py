"""Throwaway sandbox clones for ``yolo`` write-mode runs.

A yolo turn runs against a ``git clone`` under the temp dir instead of the real
clone, so the worst case is a deleted directory. When the turn ends, the
sandbox's diff is captured and recorded; the user reviews it and either promotes
(apply the patch to the real clone) or discards the sandbox.

Sandboxes live under ``HESTIA_SANDBOX_DIR`` (``/tmp`` by default) and are never
auto-promoted.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_STATE = Path(".hestia") / "sandboxes"


def base_dir() -> Path:
    return Path(os.environ.get("HESTIA_SANDBOX_DIR", tempfile.gettempdir()))


def _git(cwd: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def create(repos: list[tuple[str, Path]], label: str = "") -> dict:
    """Clone each ``(alias, path)`` into a fresh temp dir. Returns sandbox info."""
    root = Path(tempfile.mkdtemp(prefix="hestia-yolo-", dir=base_dir()))
    clones: dict[str, str] = {}
    bases: dict[str, str] = {}
    try:
        for alias, path in repos:
            dest = root / alias
            proc = _git(path, ["clone", "--quiet", "--no-hardlinks", str(path), str(dest)])
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip()[:400] or f"could not clone {alias}")
            clones[alias] = str(dest)
            bases[alias] = _git(dest, ["rev-parse", "HEAD"]).stdout.strip()
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return {"path": str(root), "repos": clones, "base": bases, "label": label, "created": int(time.time() * 1000)}


def patch(alias_path: Path, base: str) -> str:
    """Staged diff of a sandbox clone against the commit it started from."""
    _git(alias_path, ["add", "-A", "--", ".", ":!.totem", ":!.hestia"])
    return _git(alias_path, ["diff", "--cached", base]).stdout


def promote(root: Path, patch_text: str) -> dict:
    if not patch_text.strip():
        return {"applied": False, "reason": "no changes"}
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=root,
        input=patch_text,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:500] or "could not apply sandbox patch")
    return {"applied": True}


def discard(path: str | Path) -> None:
    shutil.rmtree(Path(path), ignore_errors=True)


def record(root: Path, info: dict, patches: dict[str, str]) -> None:
    state = root / _STATE
    state.mkdir(parents=True, exist_ok=True)
    (state / "latest.json").write_text(json.dumps({**info, "patches": list(patches)}, indent=2) + "\n")
    for alias, text in patches.items():
        (state / f"{alias}.patch").write_text(text)


def latest(root: Path) -> dict | None:
    try:
        info = json.loads((root / _STATE / "latest.json").read_text())
    except (OSError, ValueError):
        return None
    patches = {}
    for alias in info.get("patches", []):
        try:
            patches[alias] = (root / _STATE / f"{alias}.patch").read_text()
        except OSError:
            patches[alias] = ""
    info["patches"] = patches
    return info


def clear(root: Path) -> None:
    shutil.rmtree(root / _STATE, ignore_errors=True)
