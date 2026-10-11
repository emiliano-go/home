"""Subagent swarms and subagent write-scope enforcement."""

import pytest

from hestia.tools import subagents, workspace
from hestia.tools.registry import ProjectContext, write_allowed


def _ctx(tmp_path, **kw):
    base = dict(project_id=1, name="t", repo_url="", local_path=tmp_path, workspace_path=tmp_path)
    base.update(kw)
    return ProjectContext(**base)


def test_write_allowed_globs(tmp_path):
    ctx = _ctx(tmp_path)
    assert write_allowed(ctx, "any/path.py")
    ctx.write_allowlist = ("src/audit/**", "*.md")
    assert write_allowed(ctx, "src/audit/a.py")
    assert write_allowed(ctx, "README.md")
    assert not write_allowed(ctx, "src/main.py")


def test_workspace_write_scope_enforced(tmp_path):
    ctx = _ctx(tmp_path, write_allowlist=("notes/**",))
    assert workspace._write(ctx, "notes/a.md", "x")["bytes"] == 1
    with pytest.raises(PermissionError):
        workspace._write(ctx, "other.md", "x")


def test_run_swarm_validation(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError):
        subagents.run_swarm(ctx, None, "directive", [])
    with pytest.raises(ValueError):
        subagents.run_swarm(ctx, None, "directive", [{"nope": 1}])


def test_run_swarm_fans_out(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    seen = {}

    class Cfg:
        name = "explore"

    def fake_spawn(ctx, db, config, task, *, directive="", write_scope=None, index=None):
        seen[index] = (task, directive, write_scope)
        return {"index": index, "agent": config.name, "task": task, "run_id": f"r{index}",
                "status": "done", "summary": task, "error": ""}

    monkeypatch.setattr(subagents, "_spawn", fake_spawn)
    monkeypatch.setattr(subagents, "_resolve_config", lambda db, action, agent: Cfg())
    out = subagents.run_swarm(
        ctx, None, "audit the repo",
        [{"task": "audit a"}, {"task": "audit b"}], 2, ["src/audit/**"],
    )
    assert [r["run_id"] for r in out] == ["r0", "r1"]
    assert seen[0] == ("audit a", "audit the repo", ["src/audit/**"])
    assert seen[1][1] == "audit the repo"
