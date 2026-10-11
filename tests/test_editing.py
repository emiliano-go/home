"""Editing tools: edit, apply_patch, bash, gated by the write grade."""

import pytest

from hestia.tools import editing
from hestia.tools.registry import ProjectContext


def _ctx(tmp_path, mode="auto"):
    return ProjectContext(project_id=1, name="t", repo_url="", local_path=tmp_path, write_mode=mode)


def _registry(tmp_path, mode="auto"):
    from hestia.tools.registry import Registry

    registry = Registry()
    editing.register(registry, None)
    return registry, _ctx(tmp_path, mode)


def test_edit_replaces_unique_string(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    registry, ctx = _registry(tmp_path)
    out = registry.get("edit").handler(ctx, {"path": "a.py", "old_string": "x = 1", "new_string": "x = 10"})
    assert out["replacements"] == 1
    assert (tmp_path / "a.py").read_text() == "x = 10\ny = 2\n"


def test_edit_rejects_ambiguous_match(tmp_path):
    (tmp_path / "a.py").write_text("x\nx\n")
    registry, ctx = _registry(tmp_path)
    with pytest.raises(ValueError):
        registry.get("edit").handler(ctx, {"path": "a.py", "old_string": "x", "new_string": "y"})
    assert (tmp_path / "a.py").read_text() == "x\nx\n"


def test_apply_patch_is_atomic(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    registry, ctx = _registry(tmp_path)
    with pytest.raises(ValueError):
        registry.get("apply_patch").handler(
            ctx,
            {
                "edits": [
                    {"path": "a.py", "old_string": "x = 1", "new_string": "x = 10"},
                    {"path": "b.py", "old_string": "missing", "new_string": "z"},
                ]
            },
        )
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_bash_runs_and_reports_exit_code(tmp_path):
    registry, ctx = _registry(tmp_path)
    out = registry.get("bash").handler(ctx, {"command": "echo hello; exit 3"})
    assert out["code"] == 3 and "hello" in out["output"]


def test_read_grade_blocks_writes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    registry, ctx = _registry(tmp_path, mode="read")
    with pytest.raises(PermissionError):
        registry.get("edit").handler(ctx, {"path": "a.py", "old_string": "x", "new_string": "y"})


def test_ask_grade_blocks_without_approval(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    registry, ctx = _registry(tmp_path, mode="ask")
    with pytest.raises(PermissionError):
        registry.get("edit").handler(ctx, {"path": "a.py", "old_string": "x", "new_string": "y"})


def test_path_escape_blocked(tmp_path):
    registry, ctx = _registry(tmp_path)
    with pytest.raises(PermissionError):
        registry.get("edit").handler(ctx, {"path": "../outside.py", "old_string": "a", "new_string": "b"})
