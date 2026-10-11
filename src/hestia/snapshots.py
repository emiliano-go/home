"""Git-backed snapshots so agent edits are undoable.

A snapshot is a dangling commit whose tree captures the clone's working state
(tracked + newly added files, minus Hestia metadata). Creating one stages the
index, writes a tree, builds a commit with ``git commit-tree``, then resets the
index back to HEAD. The worktree is never touched.

Note: the reset discards any *pre-existing* staged state, so a caller that
cares about an unfinished staging area must take care of it first. Hestia
manages its clones itself, so this is not a concern in practice.

Reverting resets the index and worktree to that tree and removes files created
afterwards. Ignored files (``.gitignore``) are never removed.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

_META = (":!.totem", ":!.hestia")
_META_NAMES = (".totem", ".hestia")
_LOG = Path(".hestia") / "snapshots.jsonl"


def _git(root: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)


def _is_repo(root: Path) -> bool:
    return _git(root, ["rev-parse", "--is-inside-work-tree"]).returncode == 0


def create(root: Path, label: str = "") -> str | None:
    """Capture the working state; return the snapshot SHA, or None if unchanged."""
    if not _is_repo(root):
        return None
    if _git(root, ["add", "-A", "--", ".", *_META]).returncode != 0:
        return None
    tree = _git(root, ["write-tree"])
    if tree.returncode != 0 or not tree.stdout.strip():
        _git(root, ["reset"])
        return None
    head_tree = _git(root, ["rev-parse", "HEAD^{tree}"]).stdout.strip()
    if head_tree and tree.stdout.strip() == head_tree:
        _git(root, ["reset"])  # nothing changed since the last commit/snapshot
        return None
    commit = _git(root, ["commit-tree", tree.stdout.strip(), "-p", "HEAD", "-m", f"hestia snapshot: {label}"])
    _git(root, ["reset"])  # index back to HEAD; worktree untouched
    sha = commit.stdout.strip()
    if commit.returncode != 0 or not sha:
        return None
    _record(root, sha, label)
    return sha


def restore(root: Path, sha: str) -> dict:
    """Reset the clone's index and worktree to a snapshot, removing later files."""
    if _git(root, ["cat-file", "-e", f"{sha}^{{tree}}"]).returncode != 0:
        raise ValueError(f"unknown snapshot: {sha}")
    reset = _git(root, ["read-tree", "--reset", "-u", sha])
    if reset.returncode != 0:
        raise RuntimeError(reset.stderr.strip()[:500] or "could not restore snapshot")
    clean = _git(root, ["clean", "-fd", "-e", _META_NAMES[0], "-e", _META_NAMES[1]])
    return {"restored": sha, "removed": [line for line in clean.stdout.splitlines() if line]}


def recent(root: Path, limit: int = 20) -> list[dict]:
    path = root / _LOG
    try:
        lines = [line for line in path.read_text().splitlines() if line.strip()]
    except OSError:
        return []
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _record(root: Path, sha: str, label: str) -> None:
    path = root / _LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a") as handle:
            handle.write(json.dumps({"sha": sha, "label": label, "time": int(time.time() * 1000)}) + "\n")
    except OSError:
        pass
