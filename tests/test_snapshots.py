"""Git-backed snapshots: create, restore, list."""

import subprocess

from hestia import snapshots


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_snapshot_and_restore(tmp_path):
    root = _repo(tmp_path)
    assert snapshots.create(root, "noop") is None  # clean tree: nothing to snapshot

    (root / "a.txt").write_text("two\n")
    (root / "b.txt").write_text("added\n")
    sha = snapshots.create(root, "turn-1")
    assert sha

    (root / "a.txt").write_text("three\n")
    (root / "c.txt").write_text("later\n")
    snapshots.restore(root, sha)

    assert (root / "a.txt").read_text() == "two\n"
    assert (root / "b.txt").read_text() == "added\n"
    assert not (root / "c.txt").exists()


def test_restore_unknown_snapshot(tmp_path):
    root = _repo(tmp_path)
    try:
        snapshots.restore(root, "deadbeef")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_non_repo_returns_none(tmp_path):
    assert snapshots.create(tmp_path) is None
    assert snapshots.recent(tmp_path) == []


def test_recent_lists_labels(tmp_path):
    root = _repo(tmp_path)
    (root / "a.txt").write_text("two\n")
    snapshots.create(root, "turn-1")
    (root / "a.txt").write_text("three\n")
    snapshots.create(root, "turn-2")
    assert [entry["label"] for entry in snapshots.recent(root)] == ["turn-1", "turn-2"]
