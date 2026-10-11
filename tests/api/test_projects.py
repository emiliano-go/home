"""Project lifecycle: clone, delete cascade, streaming create, pull."""

from pathlib import Path

from hestia import config
from hestia import totem_store

from tests.api.conftest import _mk_project


def test_clone_auth_args(client, monkeypatch):
    from hestia import repos

    monkeypatch.setattr(repos.config, "github_token", lambda: "tok")
    assert repos.auth_args("https://github.com/a/b.git") == [
        "-c",
        "http.extraheader=Authorization: Bearer tok",
    ]
    assert repos.auth_args("/tmp/local/repo") == []

    monkeypatch.setattr(repos.config, "github_token", lambda: None)
    assert repos.auth_args("https://github.com/a/b.git") == []


def test_project_delete_cascade(client):
    from sqlmodel import Session as SqlSession
    from sqlmodel import select as sqlselect

    from hestia.registry.db import engine
    from hestia.registry.models import (
        Goal,
        InboxItem,
        Message,
        Milestone,
        Project,
        Reminder,
        Schedule,
        Task,
        TaskComment,
        Usage,
        Watch,
    )
    from hestia.registry.models import Session as ChatSession

    alpha = _mk_project(client, name="alpha")
    beta = _mk_project(client, name="beta")
    ws_alpha = config.workspace_dir("alpha")
    ws_beta = config.workspace_dir("beta")
    (ws_alpha / "plan.md").write_text("x")
    (ws_beta / "keep.md").write_text("x")
    repos_alpha = config.data_dir() / "repos" / "alpha"
    repos_beta = config.data_dir() / "repos" / "beta"

    task = client.post(f"/api/projects/{alpha['id']}/tasks", json={"title": "t"}).json()
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "note"})
    client.post(f"/api/projects/{alpha['id']}/goals", json={"title": "g"})
    client.post(f"/api/projects/{alpha['id']}/milestones", json={"title": "m"})
    client.post(
        f"/api/projects/{alpha['id']}/schedules",
        json={"action": "chat", "instruction": "x"},
    )
    client.post(
        "/api/reminders",
        json={"text": "r", "due_at": "2030-01-01T00:00:00+00:00", "project_id": alpha["id"]},
    )
    client.post(
        "/api/watches",
        json={"kind": "page", "url": "https://example.com", "project_id": alpha["id"]},
    )
    with SqlSession(engine()) as db:
        chat = ChatSession(project_id=alpha["id"], title="s")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        session_id = chat.id
        db.add(Message(session_id=session_id, role="user", content="hi"))
        db.add(InboxItem(project_id=alpha["id"], kind="pr", external_id="pr:1", title="x"))
        db.add(Usage(project_id=alpha["id"], action="chat", prompt_tokens=5))
        db.commit()

    client.post(f"/api/projects/{beta['id']}/tasks", json={"title": "keep"})

    assert client.delete(f"/api/projects/{alpha['id']}").status_code == 204

    with SqlSession(engine()) as db:
        for model in (Task, Goal, Milestone, Schedule, Reminder, Watch, InboxItem, Usage, ChatSession):
            assert db.exec(sqlselect(model).where(model.project_id == alpha["id"])).all() == [], model.__name__
        assert db.exec(sqlselect(Message).where(Message.session_id == session_id)).all() == []
        assert db.exec(sqlselect(TaskComment).where(TaskComment.task_id == task["id"])).all() == []
        assert db.get(Project, alpha["id"]) is None
        assert len(db.exec(sqlselect(Task).where(Task.project_id == beta["id"])).all()) == 1

    assert not repos_alpha.exists()
    assert not ws_alpha.exists()
    assert repos_beta.exists()
    assert ws_beta.exists()
    assert (ws_beta / "keep.md").exists()


def test_create_project_stream(client):
    import json
    import subprocess
    import tempfile

    src = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    (Path(src) / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
        cwd=src,
        check=True,
    )

    resp = client.post("/api/projects/stream", json={"name": "streamed", "repo_url": src})
    assert resp.status_code == 200, resp.text
    events = [
        json.loads(line[len("data:") :].strip())
        for line in resp.text.splitlines()
        if line.startswith("data:")
    ]
    assert any(
        e["event"] == "step" and e["step"] == "clone" and e.get("status") == "done"
        for e in events
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["project"]["name"] == "streamed"
    assert client.get("/api/projects").json()[0]["name"] == "streamed"


def test_create_project_stream_duplicate(client):
    project = _mk_project(client, name="dup")
    src = project["repo_url"]
    resp = client.post("/api/projects/stream", json={"name": "dup", "repo_url": src})
    assert resp.status_code == 200
    assert '"event": "error"' in resp.text


def test_pull_pending_and_inbox(client):
    import subprocess
    from pathlib import Path

    from sqlmodel import Session

    from hestia import inbox, overview
    from hestia.registry.db import engine

    project = _mk_project(client, name="pulltest")
    clone = Path(project["local_path"])
    src = Path(project["repo_url"])

    # up to date: nothing pending, ahead/behind both zero
    assert overview.pending_pull(clone, do_fetch=True) is None

    # a new upstream commit makes the clone behind by one
    (src / "new.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "more"],
        cwd=src,
        check=True,
    )

    pending = overview.pending_pull(clone, do_fetch=True)
    assert pending and pending["behind"] == 1

    # ahead/behind must not be swapped
    summary = overview.git_summary(clone)
    assert summary["behind"] == 1
    assert summary["ahead"] == 0

    # local vs remote: the remote tip is the new upstream commit
    assert summary["remote"]["ref"].endswith("master")
    assert summary["remote"]["last_commit"]["subject"] == "more"
    assert summary["last_commit"]["subject"] != "more"

    status = client.get(f"/api/projects/{project['id']}/status").json()
    assert status["git"]["remote"]["last_commit"]["subject"] == "more"

    # polling surfaces a "Pull pending" inbox item
    with Session(engine()) as db:
        inbox.check_pulls(db)
    items = client.get("/api/inbox").json()["items"]
    pulls = [i for i in items if i["kind"] == "pull"]
    assert pulls and pulls[0]["title"] == "Pull pending"
    assert "behind origin/" in pulls[0]["subtitle"]

    # pulling clears the item
    assert client.post(f"/api/projects/{project['id']}/pull").status_code == 200
    items = client.get("/api/inbox").json()["items"]
    assert not [i for i in items if i["kind"] == "pull"]


def test_project_preference_memory_always_in_context(client):
    from hestia import totem_store

    project = _mk_project(client)
    path = Path(project["local_path"])
    totem_store.create(
        path,
        type="observation",
        title="House style",
        statement="Never use em dashes.",
        tags=["preference"],
        metadata={"observation": "house_style"},
    )
    totem_store.create(
        path,
        type="observation",
        title="Client Acme",
        statement="Acme uses SSO.",
        tags=["client:acme"],
        metadata={"observation": "client_fact"},
    )
    context = totem_store.digest(path, task="anything").get("context", "")
    assert "Never use em dashes." in context
    assert "Acme uses SSO." in context


def test_allow_local_browser_roundtrip(client):
    project = _mk_project(client)
    assert project["allow_local_browser"] is False

    updated = client.put(
        f"/api/projects/{project['id']}", json={"allow_local_browser": True}
    ).json()
    assert updated["allow_local_browser"] is True

    fetched = client.get(f"/api/projects/{project['id']}").json()
    assert fetched["allow_local_browser"] is True


def test_write_mode_roundtrip(client):
    project = _mk_project(client)
    assert project["write_mode"] == ""

    updated = client.put(
        f"/api/projects/{project['id']}", json={"write_mode": "auto"}
    ).json()
    assert updated["write_mode"] == "auto"

    rejected = client.put(f"/api/projects/{project['id']}", json={"write_mode": "bogus"})
    assert rejected.status_code == 400


def test_multi_repo_create_and_endpoints(client):
    import subprocess
    import tempfile
    from pathlib import Path

    def mk(name):
        src = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=src, check=True)
        (Path(src) / f"{name}.md").write_text(f"# {name}\n")
        subprocess.run(["git", "add", "."], cwd=src, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
             "commit", "-qm", "i"],
            cwd=src, check=True,
        )
        return src

    a, b = mk("a"), mk("b")
    resp = client.post(
        "/api/projects",
        json={
            "name": "multirepo",
            "description": "two repos",
            "repos": [{"url": a, "alias": "api", "primary": True}, {"url": b, "alias": "web"}],
            "allow_local_browser": True,
        },
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["description"] == "two repos"
    assert project["repo_url"] == a and project["local_path"].endswith("/api")

    listed = client.get(f"/api/projects/{project['id']}/repos").json()
    assert [r["alias"] for r in listed] == ["api", "web"]
    assert listed[0]["is_primary"] and listed[0]["status"]["branch"]
    assert listed[1]["local_path"].endswith("/web")

    got = client.get(f"/api/projects/{project['id']}").json()
    assert got["status"]["branch"] and len(got["repos"]) == 2

    status = client.get(f"/api/projects/{project['id']}/status").json()
    assert [r["alias"] for r in status["repos"]] == ["api", "web"]
    assert status["git"]["branch"] and status["repos"][1]["git"]["branch"]

    activity = client.get(f"/api/projects/{project['id']}/activity?github=false").json()["items"]
    commits = [i for i in activity if i["kind"] == "commit"]
    assert commits and any(" · " in c["subtitle"] for c in commits)

    c = mk("cool")
    added = client.post(f"/api/projects/{project['id']}/repos", json={"url": c})
    assert added.status_code == 201, added.text
    assert added.json()["alias"] == c.rstrip("/").split("/")[-1].lower()

    pulled = client.post(f"/api/projects/{project['id']}/pull?repo=web")
    assert pulled.status_code == 200
    assert pulled.json()["results"][0]["alias"] == "web"

    added_alias = added.json()["alias"]
    assert client.delete(f"/api/projects/{project['id']}/repos/api").status_code == 204
    rows = client.get(f"/api/projects/{project['id']}/repos").json()
    assert [r["alias"] for r in rows] == ["web", added_alias]
    assert rows[0]["is_primary"]
    project = client.get(f"/api/projects/{project['id']}").json()
    assert project["repo_url"] == b


def test_workspace_only_project(client):
    resp = client.post("/api/projects", json={"name": "notes"})
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["repo_url"] == "" and project["local_path"] == ""
    assert client.get(f"/api/projects/{project['id']}/repos").json() == []
    assert client.post(f"/api/projects/{project['id']}/pull").status_code == 400


def test_snapshot_revert_roundtrip(client):
    from pathlib import Path

    from hestia import snapshots

    project = _mk_project(client)
    root = Path(project["local_path"])
    (root / "file.txt").write_text("one\n")
    assert snapshots.create(root, "test-turn")

    listing = client.get(f"/api/projects/{project['id']}/snapshots").json()
    assert listing[-1]["label"] == "test-turn"

    (root / "file.txt").write_text("two\n")
    assert client.post(f"/api/projects/{project['id']}/revert", json={}).status_code == 200
    assert (root / "file.txt").read_text() == "one\n"


def test_sandbox_promote_and_discard(client):
    from pathlib import Path

    from hestia import sandbox

    project = _mk_project(client)
    root = Path(project["local_path"])
    info = sandbox.create([("main", root)])
    clone = Path(info["repos"]["main"])
    (clone / "file.txt").write_text("sandboxed\n")
    sandbox.record(root, info, {"main": sandbox.patch(clone, info["base"]["main"])})

    assert client.get(f"/api/projects/{project['id']}/sandbox").json()["path"] == info["path"]
    assert client.post(f"/api/projects/{project['id']}/sandbox/promote", json={}).status_code == 200
    assert (root / "file.txt").read_text() == "sandboxed\n"
    assert client.post(f"/api/projects/{project['id']}/sandbox/discard", json={}).status_code == 200
