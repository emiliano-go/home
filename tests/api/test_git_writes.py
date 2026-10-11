"""Opt-in git writes: sandbox, push, and pull requests."""

from pathlib import Path

import pytest

from hestia import config

from tests.api.conftest import _mk_project


def test_git_writes_gated_and_sandboxed(client):
    import subprocess

    from hestia.tools import build_registry, gitwrites
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    assert project["allow_git_writes"] is False
    toggled = client.put(
        f"/api/projects/{project['id']}/git-writes", json={"enabled": True}
    ).json()
    assert toggled["allow_git_writes"] is True

    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    tools = {t.name: t for t in build_registry(writes=True).all()}

    written = tools["write_file"].handler(
        ctx, {"path": "src/new.py", "content": "print('hi')\n"}
    )
    assert written["path"] == "src/new.py"
    assert (Path(project["local_path"]) / "src" / "new.py").exists()

    with pytest.raises(PermissionError):
        tools["write_file"].handler(ctx, {"path": "../escape.txt", "content": "x"})
    with pytest.raises(PermissionError):
        tools["write_file"].handler(ctx, {"path": ".git/config", "content": "x"})

    assert tools["git_create_branch"].handler(ctx, {"name": "feature/test"})["branch"] == "feature/test"
    with pytest.raises(ValueError):
        tools["git_create_branch"].handler(ctx, {"name": "bad..name"})

    commit = tools["git_commit"].handler(
        ctx, {"message": "add new file", "paths": ["src/new.py"]}
    )
    assert commit["sha"] and commit["files"] == ["src/new.py"]
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=project["local_path"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert log == "add new file"
    with pytest.raises(ValueError):
        tools["git_commit"].handler(ctx, {"message": "nothing", "paths": ["README.md"]})

    # mutating tools exist only in the opted-in registry
    assert "write_file" not in {t.name for t in build_registry().all()}
    assert "write_file" in {t.name for t in build_registry(writes=True).all()}


def test_git_push_to_remote(client):
    import subprocess
    import tempfile

    from hestia.tools import build_registry
    from hestia.tools.registry import ProjectContext

    bare = tempfile.mkdtemp()
    subprocess.run(["git", "init", "--bare", "-q"], cwd=bare, check=True)
    project = _mk_project(client, name="pushy", repo_url=bare)
    client.put(f"/api/projects/{project['id']}/git-writes", json={"enabled": True})

    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    tools = {t.name: t for t in build_registry(writes=True).all()}
    tools["write_file"].handler(ctx, {"path": "hello.txt", "content": "hi\n"})
    tools["git_commit"].handler(ctx, {"message": "hello"})
    pushed = tools["git_push"].handler(ctx, {})

    branches = subprocess.run(
        ["git", "branch"], cwd=bare, capture_output=True, text=True
    ).stdout
    assert pushed["branch"] in branches


def test_open_pr_requires_token_and_payload(client, monkeypatch):
    from hestia import config
    from hestia.tools import build_registry, gitwrites
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client, name="prtest")
    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url="https://github.com/a/b",
        local_path=Path(project["local_path"]),
    )
    tools = {t.name: t for t in build_registry(writes=True).all()}

    monkeypatch.setattr(config, "github_token", lambda: None)
    with pytest.raises(PermissionError):
        tools["gh_open_pr"].handler(ctx, {"title": "x"})

    monkeypatch.setattr(config, "github_token", lambda: "tok")
    monkeypatch.setattr(gitwrites, "_default_branch", lambda slug: "main")
    captured = {}

    def fake_create_pr(slug, payload):
        captured["slug"] = slug
        captured["payload"] = payload
        return {"number": 7, "html_url": "https://github.com/a/b/pull/7"}

    monkeypatch.setattr(gitwrites, "_create_pr", fake_create_pr)
    out = tools["gh_open_pr"].handler(ctx, {"title": "Add feature", "body": "b"})
    assert out["number"] == 7 and out["base"] == "main"
    assert captured["slug"] == "a/b"
    assert captured["payload"]["title"] == "Add feature"
