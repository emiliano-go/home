"""Docs generation, triage, capture, and global search."""

from pathlib import Path

from hestia import config
from hestia import totem_store

from tests.api.conftest import _mk_project, _mk_provider


def test_triage_creates_task_and_plan(client, monkeypatch):
    from hestia import overview
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    agent = client.post(
        "/api/agents", json={"name": "triager", "provider_id": provider["id"]}
    ).json()
    client.put("/api/actions/triage", json={"agent_id": agent["id"]})

    monkeypatch.setattr(
        overview,
        "github_item_for_url",
        lambda repo_url, kind, number: {
            "kind": "issue",
            "number": number,
            "title": "Support plugins",
            "body": "We need a plugin system.",
            "state": "open",
            "user": "eve",
            "url": "https://github.com/a/b/issues/7",
            "labels": ["enhancement"],
        },
    )

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        system = messages[0]["content"]
        assert "Support plugins" in system
        assert "plans/issue-7.md" in system
        assert {t.name for t in registry.all()} >= {"task_create", "workspace_write"}
        yield {"type": "message", "content": "Plan written and 2 tasks created.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/triage", json={"kind": "issue", "number": 7}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report"] == "Plan written and 2 tasks created."
    assert body["path"] == "plans/issue-7.md"
    assert body["task_id"]

    tasks = client.get(f"/api/projects/{project['id']}/tasks").json()
    assert any(t["title"].startswith("#7 Support plugins") for t in tasks)

    assert client.post(
        f"/api/projects/{project['id']}/triage", json={"kind": "issue"}
    ).status_code == 400


def test_docs_generation(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    agent = client.post(
        "/api/agents", json={"name": "writer", "provider_id": provider["id"]}
    ).json()
    client.put("/api/actions/docs", json={"agent_id": agent["id"]})

    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["system"] = messages[0]["content"]
        seen["tools"] = {t.name for t in registry.all()}
        yield {"type": "message", "content": "Wrote ARCHITECTURE.md", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(f"/api/projects/{project['id']}/docs", json={"kind": "architecture"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "report": "Wrote ARCHITECTURE.md",
        "path": "ARCHITECTURE.md",
        "kind": "architecture",
    }
    assert "ARCHITECTURE.md" in seen["system"]
    assert {"workspace_write", "memory_search"} <= seen["tools"]

    resp = client.post(
        f"/api/projects/{project['id']}/docs",
        json={"kind": "adr", "topic": "Use SQLite"},
    )
    assert resp.json()["path"] == "adr/use-sqlite.md"

    assert client.post(
        f"/api/projects/{project['id']}/docs", json={"kind": "adr"}
    ).status_code == 400
    assert client.post(
        f"/api/projects/{project['id']}/docs", json={"kind": "nope"}
    ).status_code == 400
    assert client.post("/api/projects/999/docs", json={}).status_code == 404


def test_capture_endpoint(client, monkeypatch):
    from hestia.routers import capture as capture_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    seen = {}

    async def fake_run_once(project_, provider_, system, user, groups="", max_turns=8, tasks_db=None):
        seen["system"] = system
        seen["user"] = user
        seen["groups"] = groups
        return "Created task #5 and memory 'Acme'.", None, {}

    monkeypatch.setattr(capture_router, "run_once", fake_run_once)
    resp = client.post(
        f"/api/projects/{project['id']}/capture",
        json={"text": "Call Acme about renewal tomorrow.", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert "Acme" in resp.json()["report"]
    assert "task_create" in seen["system"] and "remind_me" in seen["system"]
    assert "tasks" in seen["groups"]

    assert (
        client.post(
            f"/api/projects/{project['id']}/capture",
            json={"text": "   ", "provider_id": provider["id"]},
        ).status_code
        == 400
    )


def test_global_search(client):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.registry.models import Session as ChatSession

    alpha = _mk_project(client, name="alpha")
    beta = _mk_project(client, name="beta")
    (config.workspace_dir("alpha") / "notes.md").write_text(
        "The quartz migration plan\n", encoding="utf-8"
    )
    totem_store.create(
        Path(alpha["local_path"]),
        type="decision",
        title="Quartz choice",
        statement="We chose quartz for the scheduler.",
        tags=["t"],
    )
    with SqlSession(engine()) as db:
        db.add(ChatSession(project_id=beta["id"], title="Quartz rollout chat"))
        db.commit()

    data = client.get("/api/search", params={"q": "quartz"}).json()
    assert any(m["title"] == "Quartz choice" and m["project"] == "alpha" for m in data["memories"])
    assert any(f["path"] == "notes.md" and f["project"] == "alpha" for f in data["files"])
    assert any(s["title"] == "Quartz rollout chat" and s["project"] == "beta" for s in data["sessions"])

    assert client.get("/api/search", params={"q": "zzznothing"}).json() == {
        "query": "zzznothing",
        "memories": [],
        "files": [],
        "sessions": [],
    }
