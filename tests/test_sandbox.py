"""Yolo sandbox clones: create, patch, promote, discard, record."""

import subprocess
from pathlib import Path

from hestia import sandbox


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_create_edit_patch_promote(tmp_path):
    root = _repo(tmp_path)
    info = sandbox.create([("main", root)], label="turn-1")
    clone = Path(info["repos"]["main"])
    (clone / "a.txt").write_text("two\n")
    (clone / "new.txt").write_text("x\n")

    patch = sandbox.patch(clone, info["base"]["main"])
    assert "two" in patch and "new.txt" in patch
    assert (root / "a.txt").read_text() == "one\n"  # real clone untouched

    assert sandbox.promote(root, patch)["applied"] is True
    assert (root / "a.txt").read_text() == "two\n"
    assert (root / "new.txt").read_text() == "x\n"

    sandbox.discard(info["path"])
    assert not Path(info["path"]).exists()


def test_record_and_latest(tmp_path):
    root = _repo(tmp_path)
    info = sandbox.create([("main", root)])
    clone = Path(info["repos"]["main"])
    (clone / "a.txt").write_text("two\n")
    sandbox.record(root, info, {"main": sandbox.patch(clone, info["base"]["main"])})

    latest = sandbox.latest(root)
    assert latest and "two" in latest["patches"]["main"]

    sandbox.clear(root)
    assert sandbox.latest(root) is None
    sandbox.discard(info["path"])
