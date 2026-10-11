"""Task board, comments, review gates, and milestones."""

from pathlib import Path

import pytest

from tests.api.conftest import _mk_project, _mk_provider


def test_task_crud(client):
    project = _mk_project(client)
    pid = project["id"]
    assert client.get(f"/api/projects/{pid}/tasks").json() == []

    t1 = client.post(f"/api/projects/{pid}/tasks", json={"title": "Write tests"}).json()
    assert t1["status"] == "backlog" and t1["priority"] == "medium"
    t2 = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "Ship it", "status": "doing", "priority": "high"},
    ).json()
    assert t2["status"] == "doing"

    assert client.post(f"/api/projects/{pid}/tasks", json={"title": "x", "status": "nope"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/tasks", json={"title": "  "}).status_code == 400

    moved = client.put(
        f"/api/tasks/{t1['id']}", json={"status": "done", "title": "Write more tests"}
    ).json()
    assert moved["status"] == "done" and moved["title"] == "Write more tests"

    assert client.delete(f"/api/tasks/{t2['id']}").status_code == 204
    assert [t["id"] for t in client.get(f"/api/projects/{pid}/tasks").json()] == [t1["id"]]
    assert client.get("/api/projects/999/tasks").status_code == 404


def test_task_agent_tools(client):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.tools import tasks as task_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    with SqlSession(engine()) as db:
        tools = {t.name: t for t in task_tools.make_tools(db)}
        created = tools["task_create"].handler(ctx, {"title": "From agent", "status": "todo"})
        assert created["status"] == "todo"
        assert any(t["id"] == created["id"] for t in tools["task_list"].handler(ctx, {}))
        moved = tools["task_update"].handler(ctx, {"id": created["id"], "status": "done"})
        assert moved["status"] == "done"
        tools["task_delete"].handler(ctx, {"id": created["id"]})
        assert tools["task_list"].handler(ctx, {}) == []


def test_task_agent_milestone_tools(client):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.tools import tasks as task_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    with SqlSession(engine()) as db:
        tools = {t.name: t for t in task_tools.make_tools(db)}
        milestone = tools["milestone_create"].handler(ctx, {"title": "Beta"})
        assert milestone["title"] == "Beta"
        created = tools["task_create"].handler(
            ctx, {"title": "ship", "milestone_id": milestone["id"]}
        )
        assert created["milestone_id"] == milestone["id"]
        listed = tools["milestone_list"].handler(ctx, {})
        assert listed[0]["progress"]["total"] == 1
        moved = tools["milestone_update"].handler(
            ctx, {"id": milestone["id"], "status": "done"}
        )
        assert moved["status"] == "done"


def test_task_dependencies(client):
    project = _mk_project(client)
    pid = project["id"]
    a = client.post(f"/api/projects/{pid}/tasks", json={"title": "a"}).json()
    b = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "b", "depends_on": [a["id"]]}
    ).json()
    assert b["depends_on"] == [a["id"]]
    assert b["blocked_by"] == [a["id"]]

    ready = client.get(f"/api/projects/{pid}/tasks", params={"ready": "true"}).json()
    assert {t["id"] for t in ready} == {a["id"]}

    client.put(f"/api/tasks/{a['id']}", json={"status": "done"})
    tasks = {t["id"]: t for t in client.get(f"/api/projects/{pid}/tasks").json()}
    assert tasks[b["id"]]["blocked_by"] == []
    ready = client.get(f"/api/projects/{pid}/tasks", params={"ready": "true"}).json()
    assert {t["id"] for t in ready} == {b["id"]}

    # self-dependency, unknown id, cross-project id, and cycles are rejected
    assert client.post(
        f"/api/projects/{pid}/tasks", json={"title": "x", "depends_on": [999]}
    ).status_code == 400
    assert client.put(f"/api/tasks/{a['id']}", json={"depends_on": [a["id"]]}).status_code == 400
    assert client.put(f"/api/tasks/{a['id']}", json={"depends_on": [b["id"]]}).status_code == 400
    other = _mk_project(client, name="other")
    d = client.post(f"/api/projects/{other['id']}/tasks", json={"title": "d"}).json()
    assert client.put(f"/api/tasks/{a['id']}", json={"depends_on": [d["id"]]}).status_code == 400

    # deleting a task removes it from other tasks' dependencies
    c = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "c", "depends_on": [b["id"]]}
    ).json()
    client.delete(f"/api/tasks/{b['id']}")
    tasks = {t["id"]: t for t in client.get(f"/api/projects/{pid}/tasks").json()}
    assert tasks[c["id"]]["depends_on"] == []
    assert tasks[c["id"]]["blocked_by"] == []


def test_task_review_gate(client):
    project = _mk_project(client)
    pid = project["id"]
    plain = client.post(f"/api/projects/{pid}/tasks", json={"title": "plain"}).json()
    assert client.put(f"/api/tasks/{plain['id']}", json={"status": "done"}).status_code == 200

    gated = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "gated", "acceptance": "tests pass"},
    ).json()
    assert gated["acceptance"] == "tests pass"
    resp = client.put(f"/api/tasks/{gated['id']}", json={"status": "done"})
    assert resp.status_code == 400
    assert "reviewed" in resp.json()["detail"]

    moved = client.put(
        f"/api/tasks/{gated['id']}", json={"status": "done", "reviewed": True}
    ).json()
    assert moved["status"] == "done"
    # already done: editing without reviewed is fine
    assert client.put(f"/api/tasks/{gated['id']}", json={"title": "gated v2"}).status_code == 200


def test_task_comments(client):
    project = _mk_project(client)
    pid = project["id"]
    task = client.post(f"/api/projects/{pid}/tasks", json={"title": "t"}).json()

    assert client.get(f"/api/tasks/{task['id']}/comments").json() == []
    created = client.post(
        f"/api/tasks/{task['id']}/comments", json={"body": "started"}
    ).json()
    assert created["author"] == "you" and created["body"] == "started"
    assert client.post(f"/api/tasks/{task['id']}/comments", json={"body": " "}).status_code == 400

    items = client.get(f"/api/tasks/{task['id']}/comments").json()
    assert [c["body"] for c in items] == ["started"]
    assert client.get("/api/tasks/999/comments").status_code == 404


def test_task_agent_get_and_comment(client):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.tools import tasks as task_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    with SqlSession(engine()) as db:
        tools = {t.name: t for t in task_tools.make_tools(db)}
        created = tools["task_create"].handler(
            ctx, {"title": "with acceptance", "acceptance": "green CI"}
        )
        assert created["acceptance"] == "green CI"
        tools["task_comment"].handler(ctx, {"id": created["id"], "body": "note"})
        fetched = tools["task_get"].handler(ctx, {"id": created["id"]})
        assert fetched["comments"][0]["author"] == "agent"
        assert fetched["comments"][0]["body"] == "note"
        with pytest.raises(ValueError):
            tools["task_update"].handler(ctx, {"id": created["id"], "status": "done"})
        moved = tools["task_update"].handler(
            ctx, {"id": created["id"], "status": "done", "reviewed": True}
        )
        assert moved["status"] == "done"


def test_suggest_next_work(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        registry.get("task_create").handler(
            ctx,
            {
                "title": "Add caching",
                "acceptance": "cache hit rate over 50%",
                "priority": "high",
                "source": "suggested",
            },
        )
        yield {"type": "message", "content": "Proposed 1 task.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/tasks/suggest",
        json={"provider_id": provider["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report"] == "Proposed 1 task."
    assert len(body["task_ids"]) == 1
    tasks = client.get(f"/api/projects/{project['id']}/tasks").json()
    assert tasks[0]["source"] == "suggested"

    assert client.post(f"/api/projects/{project['id']}/tasks/suggest", json={}).status_code == 400


def test_task_due_date_roundtrip_and_at_risk(client):
    from datetime import datetime, timedelta, timezone

    from sqlmodel import Session as SqlSession

    from hestia import taskboard
    from hestia.registry.db import engine

    project = _mk_project(client)
    pid = project["id"]
    past = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()

    overdue = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "ship it", "due_at": past}
    ).json()
    assert overdue["due_at"].startswith(past)

    client.post(
        f"/api/projects/{pid}/tasks", json={"title": "later", "due_at": far}
    )

    with SqlSession(engine()) as db:
        risky = taskboard.at_risk(db, pid)
        assert [t.id for t in risky] == [overdue["id"]]

    cleared = client.put(f"/api/tasks/{overdue['id']}", json={"due_at": ""}).json()
    assert cleared["due_at"] is None


def test_task_transition_emits_event(client):
    from sqlmodel import Session as SqlSession, select

    from hestia.registry.db import engine
    from hestia.registry.models import Event

    project = _mk_project(client)
    pid = project["id"]
    task = client.post(f"/api/projects/{pid}/tasks", json={"title": "review me"}).json()
    client.put(f"/api/tasks/{task['id']}", json={"status": "review"})
    with SqlSession(engine()) as db:
        rows = db.exec(
            select(Event).where(Event.project_id == pid, Event.kind == "task_review")
        ).all()
        assert rows and rows[0].key == f"task:{task['id']}:review"


def test_task_pr_url_roundtrip(client):
    project = _mk_project(client)
    task = client.post(
        f"/api/projects/{project['id']}/tasks", json={"title": "pr task"}
    ).json()
    updated = client.put(
        f"/api/tasks/{task['id']}", json={"pr_url": "https://github.com/a/b/pull/7"}
    ).json()
    assert updated["pr_url"] == "https://github.com/a/b/pull/7"


def test_run_next_picks_ready_task(client, monkeypatch):
    from sqlmodel import Session as SqlSession, select

    from hestia import jobs
    from hestia.registry.db import engine
    from hestia.registry.models import BackgroundTask, Task

    project = _mk_project(client)
    pid = project["id"]
    client.put(f"/api/projects/{pid}/git-writes", json={"enabled": True})
    monkeypatch.setattr(jobs.manager, "enqueue", lambda job_id: None)

    dep = client.post(f"/api/projects/{pid}/tasks", json={"title": "dep"}).json()
    low = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "low ready", "status": "todo", "priority": "low"},
    ).json()
    high = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "high ready", "status": "todo", "priority": "high"},
    ).json()
    blocked = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "blocked", "status": "todo", "priority": "high", "depends_on": [dep["id"]]},
    ).json()

    result = client.post(f"/api/projects/{pid}/tasks/run-next").json()
    assert result["task_id"] == high["id"], result

    with SqlSession(engine()) as db:
        job = db.get(BackgroundTask, result["job_id"])
        assert job.kind == "agent" and job.action == "implement"
        assert db.get(Task, high["id"]).status == "doing"
        assert db.get(Task, blocked["id"]).status == "todo"


def test_implement_requires_git_writes(client):
    project = _mk_project(client)
    task = client.post(
        f"/api/projects/{project['id']}/tasks", json={"title": "do it"}
    ).json()
    assert client.post(f"/api/tasks/{task['id']}/implement").status_code == 403


def test_milestone_crud_and_progress(client):
    project = _mk_project(client)
    pid = project["id"]
    assert client.get(f"/api/projects/{pid}/milestones").json() == []

    milestone = client.post(
        f"/api/projects/{pid}/milestones",
        json={"title": "v1.0", "description": "First release", "target_date": "2026-12-01"},
    ).json()
    assert milestone["status"] == "open"
    assert milestone["memories"] == []
    assert milestone["progress"]["total"] == 0

    t1 = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "a", "milestone_id": milestone["id"]}
    ).json()
    assert t1["milestone_id"] == milestone["id"]
    client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "b", "milestone_id": milestone["id"], "status": "done"},
    )

    listed = client.get(f"/api/projects/{pid}/milestones").json()
    assert listed[0]["progress"]["total"] == 2
    assert listed[0]["progress"]["done"] == 1
    assert listed[0]["progress"]["percent"] == 50

    updated = client.put(
        f"/api/milestones/{milestone['id']}",
        json={"status": "done", "memories": [{"id": "mem-1", "title": "Use sqlite"}]},
    ).json()
    assert updated["status"] == "done"
    assert updated["memories"] == [{"id": "mem-1", "title": "Use sqlite"}]

    assert client.post(f"/api/projects/{pid}/milestones", json={"title": "  "}).status_code == 400

    # deleting a milestone detaches its tasks instead of deleting them
    assert client.delete(f"/api/milestones/{milestone['id']}").status_code == 204
    assert all(t["milestone_id"] is None for t in client.get(f"/api/projects/{pid}/tasks").json())
    assert client.get(f"/api/projects/{pid}/milestones").json() == []
