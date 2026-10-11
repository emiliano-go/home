"""GitHub listing, issue sync, review, and token handling."""

from tests.api.conftest import _mk_project, _mk_provider


def test_github_list_unavailable(client):
    project = _mk_project(client)
    data = client.get(f"/api/projects/{project['id']}/github", params={"kind": "prs"}).json()
    assert data["available"] is False
    assert data["items"] == []
    assert client.get(
        f"/api/projects/{project['id']}/github", params={"kind": "bogus"}
    ).status_code == 400


def test_issue_sync(client, monkeypatch):
    from hestia import issuesync

    project = _mk_project(client)
    pid = project["id"]
    client.post(
        f"/api/projects/{pid}/tasks", json={"title": "ship", "acceptance": "green CI"}
    )

    # gated by git writes
    assert client.post(f"/api/projects/{pid}/issues/sync", json={}).status_code == 403
    client.put(f"/api/projects/{pid}/git-writes", json={"enabled": True})
    # local repo has no GitHub slug
    assert client.post(f"/api/projects/{pid}/issues/sync", json={}).status_code == 400

    monkeypatch.setattr(issuesync.overview, "repo_slug", lambda url: "a/b")
    captured = []

    def fake_create(slug, payload):
        captured.append((slug, payload))
        return {"number": 42, "html_url": "https://github.com/a/b/issues/42"}

    monkeypatch.setattr(issuesync, "_create_issue", fake_create)

    resp = client.post(f"/api/projects/{pid}/issues/sync", json={}).json()
    assert resp["created"][0]["issue"] == 42
    assert captured[0][0] == "a/b"
    assert "green CI" in captured[0][1]["body"]

    # idempotent: already-synced tasks are skipped
    resp = client.post(f"/api/projects/{pid}/issues/sync", json={}).json()
    assert resp["created"] == [] and resp["skipped"] == 1
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    assert tasks[0]["github_issue"] == 42


def test_github_review(client, monkeypatch):
    from hestia import overview
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    monkeypatch.setattr(
        overview,
        "github_item_for_url",
        lambda repo_url, kind, number: {
            "kind": "pr",
            "number": number,
            "title": "Add caching",
            "body": "Cache the thing.",
            "state": "open",
            "user": "eve",
            "url": "https://github.com/a/b/pull/5",
            "branch": "cache",
        },
    )
    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["system"] = messages[0]["content"]
        seen["tools"] = {t.name for t in registry.all()}
        yield {"type": "message", "content": "LGTM with nits.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/github/review",
        json={"kind": "pr", "number": 5, "provider_id": provider["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"report": "LGTM with nits.", "path": "reviews/pr-5.md"}
    assert "reviews/pr-5.md" in seen["system"]
    assert "task_create" in seen["tools"]

    assert client.post(
        f"/api/projects/{project['id']}/github/review", json={"kind": "pr"}
    ).status_code == 400


def test_github_token_storage_and_status(client, monkeypatch):
    from hestia import github_auth

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert client.get("/api/github/status").json()["connected"] is False

    class FakeResp:
        status_code = 200
        headers = {"x-oauth-scopes": "repo, read:org"}

        def json(self):
            return {"login": "octocat", "name": "Mona", "avatar_url": "https://a"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(github_auth.httpx, "get", lambda url, **kw: FakeResp())
    resp = client.post("/api/github/token", json={"token": "ghp_x"}).json()
    assert resp["connected"] is True and resp["login"] == "octocat"
    assert github_auth.load_token() == "ghp_x"

    status = client.get("/api/github/status").json()
    assert status["source"] == "stored"
    assert status["scopes"] == ["repo", "read:org"]

    # env var takes precedence
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert client.get("/api/github/status").json()["source"] == "env"

    class BadResp(FakeResp):
        status_code = 401

    monkeypatch.setattr(github_auth.httpx, "get", lambda url, **kw: BadResp())
    assert client.post("/api/github/token", json={"token": "bad"}).status_code == 400

    monkeypatch.delenv("GITHUB_TOKEN")
    client.delete("/api/github/token")
    assert github_auth.load_token() is None


def test_github_import_gh(client, monkeypatch):
    from types import SimpleNamespace

    from hestia import github_auth

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    class FakeResp:
        status_code = 200
        headers = {}

        def json(self):
            return {"login": "octocat", "name": None, "avatar_url": None}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(github_auth.httpx, "get", lambda url, **kw: FakeResp())
    monkeypatch.setattr(github_auth, "gh_cli_available", lambda: True)
    monkeypatch.setattr(
        github_auth.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ghp_gh\n"),
    )
    assert client.post("/api/github/import-gh").json()["login"] == "octocat"
    assert github_auth.load_token() == "ghp_gh"

    monkeypatch.setattr(
        github_auth.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    assert client.post("/api/github/import-gh").status_code == 400


def test_github_merge(client, monkeypatch):
    import httpx
    from sqlmodel import Session as SqlSession, select

    from hestia.registry.db import engine
    from hestia.registry.models import ProjectRepo

    project = _mk_project(client)
    with SqlSession(engine()) as db:
        rows = db.exec(
            select(ProjectRepo).where(ProjectRepo.project_id == project["id"])
        ).all()
        for row in rows:
            row.repo_url = "https://github.com/a/b"
            db.add(row)
        db.commit()

    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {"merged": True, "sha": "abc123", "message": "Pull Request successfully merged"}

    def fake_put(url, headers=None, json=None, timeout=None):
        captured.update({"url": url, "json": json})
        return FakeResponse()

    monkeypatch.setattr(httpx, "put", fake_put)
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    resp = client.post(
        f"/api/projects/{project['id']}/github/merge",
        json={"number": 5, "method": "squash"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["merged"] and body["sha"] == "abc123"
    assert captured["url"].endswith("/repos/a/b/pulls/5/merge")
    assert captured["json"] == {"merge_method": "squash"}
