"""Activity feed, project open, and status board endpoints."""

from pathlib import Path

from hestia import config
from hestia import totem_store

from tests.api.conftest import _mk_project


def test_activity_empty(client):
    data = client.get("/api/activity").json()
    assert data["counts"] == {"projects": 0, "sessions": 0, "files": 0}
    assert data["projects"] == []
    assert data["sessions"] == []
    assert data["files"] == []


def test_open_project_and_activity(client):
    project = _mk_project(client)
    (config.workspace_dir(project["name"]) / "plan.md").write_text("hi\n")

    resp = client.post(f"/api/projects/{project['id']}/open")
    assert resp.status_code == 200
    assert resp.json()["last_opened_at"]

    data = client.get("/api/activity").json()
    assert data["counts"] == {"projects": 1, "sessions": 0, "files": 1}
    assert data["projects"][0]["id"] == project["id"]
    assert data["projects"][0]["last_opened_at"]
    assert data["files"][0]["path"] == "plan.md"
    assert data["files"][0]["project"] == "demo"


def test_open_returns_previous_opened_at(client):
    project = _mk_project(client)
    first = client.post(f"/api/projects/{project['id']}/open").json()
    assert first["previous_opened_at"] is None
    assert first["last_opened_at"]
    second = client.post(f"/api/projects/{project['id']}/open").json()
    assert second["previous_opened_at"] == first["last_opened_at"]


def test_status_board(client):
    project = _mk_project(client)
    pid = project["id"]
    client.post(f"/api/projects/{pid}/tasks", json={"title": "one", "status": "doing"})

    data = client.get(f"/api/projects/{pid}/status").json()
    assert data["git"]["branch"] in ("master", "main")
    assert data["git"]["last_commit"]["subject"] == "i"
    assert data["github"]["available"] is False
    assert data["tasks"]["total"] == 1
    assert data["tasks"]["by_status"]["doing"] == 1
    assert data["changes"]["first_visit"] is True


def test_status_since_and_activity(client):
    project = _mk_project(client)
    pid = project["id"]
    (config.workspace_dir(project["name"]) / "plan.md").write_text("hi\n")
    totem_store.create(
        Path(project["local_path"]), type="gotcha", title="A gotcha", statement="x", tags=["t"]
    )

    data = client.get(
        f"/api/projects/{pid}/status", params={"since": "1970-01-01T00:00:00+00:00"}
    ).json()
    assert data["changes"]["first_visit"] is False
    counts = data["changes"]["counts"]
    assert counts["files"] >= 1
    assert counts["memories"] >= 1
    assert counts["commits"] >= 1

    items = client.get(
        f"/api/projects/{pid}/activity", params={"github": "false"}
    ).json()["items"]
    kinds = {i["kind"] for i in items}
    assert {"file", "memory", "commit"} <= kinds
