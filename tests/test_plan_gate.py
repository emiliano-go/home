"""Plan-first gate: writes need a plan and a drift check after each step."""

from pathlib import Path

from hestia.agent.loop import _execute
from hestia.tools import build_registry, plan
from hestia.tools.registry import ProjectContext, Registry, Tool, schema


def make_ctx(tmp_path, **overrides):
    kwargs = dict(
        project_id=1,
        name="t",
        repo_url="",
        local_path=tmp_path,
        workspace_path=tmp_path,
        require_plan=True,
    )
    kwargs.update(overrides)
    return ProjectContext(**kwargs)


def with_write_tool(registry, calls):
    registry.register(Tool(
        name="write_file",
        description="",
        parameters=schema({}, []),
        handler=lambda ctx, args: calls.append(args),
        effect="write",
    ))
    return registry


def test_gate_blocks_until_plan_exists(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = []
    registry = with_write_tool(build_registry(), calls)

    ok, msg = _execute(registry, ctx, "write_file", {"path": "a"})
    assert not ok and "plan_write" in msg
    assert calls == []

    ok, _ = _execute(registry, ctx, "plan_write", {"summary": "s", "steps": ["one", "two"]})
    assert ok
    ok, _ = _execute(registry, ctx, "write_file", {"path": "a"})
    assert ok
    assert calls == [{"path": "a"}]
    assert (tmp_path / "plans" / "current.md").exists()


def test_gate_requires_drift_check_after_each_write(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = []
    registry = with_write_tool(build_registry(), calls)
    _execute(registry, ctx, "plan_write", {"summary": "s", "steps": ["one"]})

    assert _execute(registry, ctx, "write_file", {})[0]
    ok, msg = _execute(registry, ctx, "write_file", {})
    assert not ok and "plan_update" in msg
    assert len(calls) == 1

    ok, _ = _execute(registry, ctx, "plan_update", {"step": 1, "status": "done", "notes": "no drift"})
    assert ok
    assert _execute(registry, ctx, "write_file", {})[0]

    content = (tmp_path / "plans" / "current.md").read_text()
    assert "1. [x] one" in content
    assert "## Drift log" in content
    assert "step 1 done: no drift" in content


def test_gate_off_does_not_block(tmp_path):
    ctx = make_ctx(tmp_path, require_plan=False)
    ctx.plan_check_pending = True
    registry = with_write_tool(build_registry(), [])
    assert _execute(registry, ctx, "write_file", {})[0]


def test_subagent_registry_is_exempt(tmp_path):
    ctx = make_ctx(tmp_path)
    calls = []
    sub = with_write_tool(Registry(), calls)
    assert _execute(sub, ctx, "write_file", {})[0]
    assert calls == [{}]


def test_plan_update_unknown_step_and_status(tmp_path):
    ctx = make_ctx(tmp_path)
    registry = build_registry()
    _execute(registry, ctx, "plan_write", {"summary": "s", "steps": ["one"]})
    ok, msg = _execute(registry, ctx, "plan_update", {"step": 9, "status": "done"})
    assert not ok and "step 9" in msg
    ok, msg = _execute(registry, ctx, "plan_update", {"step": 1, "status": "nope"})
    assert not ok and "unknown status" in msg


def test_plan_tools_present_in_default_registry():
    registry = build_registry()
    assert registry.get("plan_write") and registry.get("plan_update") and registry.get("plan_read")
    assert registry.readonly().get("plan_write") is None
