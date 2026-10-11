"""Workspace browsing, gallery, and raw file serving."""

from hestia import config

from tests.api.conftest import _mk_project


def test_workspace_list_and_read(client):
    project = _mk_project(client)
    ws = config.workspace_dir(project["name"])
    (ws / "plans").mkdir(parents=True)
    (ws / "plans" / "auth.md").write_text("# Auth plan\n")

    resp = client.get(f"/api/projects/{project['id']}/workspace")
    assert resp.json()["files"] == [{"path": "plans/auth.md", "bytes": len("# Auth plan\n")}]

    resp = client.get(f"/api/projects/{project['id']}/workspace/file", params={"path": "plans/auth.md"})
    assert resp.status_code == 200
    assert resp.text == "# Auth plan\n"

    resp = client.get(f"/api/projects/{project['id']}/workspace/file", params={"path": "../README.md"})
    assert resp.status_code == 404


def test_gallery(client):
    project = _mk_project(client)
    (config.workspace_dir(project["name"]) / "spec.md").write_text("spec\n")
    entries = client.get("/api/gallery").json()
    assert entries == [
        {"project_id": project["id"], "project": "demo", "path": "spec.md", "bytes": 5}
    ]


def test_workspace_raw_serves_images(client):
    project = _mk_project(client)
    ws = config.workspace_dir(project["name"])
    (ws / "images").mkdir(parents=True)
    (ws / "images" / "fox.png").write_bytes(b"\x89PNG\r\n\x1a\nx")

    resp = client.get(
        f"/api/projects/{project['id']}/workspace/raw", params={"path": "images/fox.png"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")

    resp = client.get(
        f"/api/projects/{project['id']}/workspace/raw", params={"path": "../x"}
    )
    assert resp.status_code == 404
