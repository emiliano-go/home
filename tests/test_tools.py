"""Sandbox and read-only enforcement tests for the tool registry."""

import subprocess

import pytest

from hestia.tools import build_registry
from hestia.tools.registry import ProjectContext


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "AGENTS.md").write_text("# Agent instructions\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return ProjectContext(project_id=1, name="t", repo_url="https://github.com/a/b", local_path=tmp_path)


@pytest.fixture
def registry():
    return build_registry()


def test_git_log_and_status(registry, repo):
    out = registry.get("git_log").handler(repo, {"max_count": 5, "oneline": True})
    assert "init" in out


def test_read_file_and_list(registry, repo):
    out = registry.get("read_file").handler(repo, {"path": "src/app.py"})
    assert out["content"] == "print('hello')\n"
    files = registry.get("list_files").handler(repo, {"pattern": "src/**/*.py"})
    assert files == ["src/app.py"]


def test_grep(registry, repo):
    hits = registry.get("grep").handler(repo, {"pattern": "hello"})
    assert hits and hits[0]["line"] == 1


def test_read_agents_md(registry, repo):
    out = registry.get("read_agents_md").handler(repo, {})
    assert out["content"].startswith("# Agent instructions")


def test_path_escape_blocked(registry, repo):
    with pytest.raises(PermissionError):
        registry.get("read_file").handler(repo, {"path": "../../etc/passwd"})


def test_mutating_git_blocked(registry, repo):
    from hestia.tools.repo import _git

    with pytest.raises(PermissionError):
        _git(repo, ["push"])
    with pytest.raises(PermissionError):
        _git(repo, ["-c", "core.sshCommand=evil", "status"])


def test_memory_create_via_tool(registry, repo):
    out = registry.get("memory_create").handler(repo, {
        "type": "decision",
        "title": "T",
        "statement": "S",
        "tags": ["x"],
    })
    assert out["id"]
    results = registry.get("memory_search").handler(repo, {"query": "T"})
    assert any(r["id"] == out["id"] for r in results)


def test_workspace_write_read_list_and_escape(registry, repo, tmp_path):
    from hestia import config

    ws = config.workspace_dir("t")
    ctx = repo.__class__(repo.project_id, repo.name, repo.repo_url, repo.local_path, ws)
    out = registry.get("workspace_write").handler(ctx, {"path": "plans/spec.md", "content": "# Spec\n"})
    assert out["bytes"] == 7
    assert (ws / "plans" / "spec.md").read_text() == "# Spec\n"
    assert registry.get("workspace_read").handler(ctx, {"path": "plans/spec.md"})["content"] == "# Spec\n"
    assert registry.get("workspace_list").handler(ctx, {"pattern": "plans/*.md"}) == ["plans/spec.md"]
    with pytest.raises(PermissionError):
        registry.get("workspace_write").handler(ctx, {"path": "../../evil.md", "content": "x"})


def test_memory_relate_relations_history_via_tools(registry, repo):
    a = registry.get("memory_create").handler(repo, {
        "type": "decision", "title": "A", "statement": "claim A", "tags": ["x"],
        "scope": "project", "asserted_by": "user",
    })
    b = registry.get("memory_create").handler(repo, {
        "type": "gotcha", "title": "B", "statement": "claim B", "tags": ["x"],
    })
    rel = registry.get("memory_relate").handler(repo, {
        "from_id": a["id"], "to_id": b["id"], "kind": "depends_on",
    })
    assert rel["kind"] == "depends_on"

    relations = registry.get("memory_relations").handler(repo, {"id": a["id"]})
    assert any(r["to_id"] == b["id"] for r in relations)

    history = registry.get("memory_history").handler(repo, {"id": a["id"]})
    assert any(h["event"] == "related" for h in history)
