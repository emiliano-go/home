"""Notifications and the GitHub inbox poller."""

from pathlib import Path

from tests.api.conftest import _mk_project


def test_notify_status_and_test(client, monkeypatch):
    from hestia import notify

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(
        notify.httpx, "post", lambda url, **kw: calls.append((url, kw)) or FakeResp()
    )

    assert client.get("/api/notify/status").json() == {
        "configured": [],
        "channels": {"ntfy": False, "telegram": False},
    }
    assert client.post("/api/notify/test").status_code == 400

    monkeypatch.setenv("NTFY_URL", "https://ntfy.example")
    monkeypatch.setenv("NTFY_TOPIC", "home")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    status = client.get("/api/notify/status").json()
    assert set(status["configured"]) == {"ntfy", "telegram"}

    result = client.post("/api/notify/test").json()
    assert result["ntfy"]["ok"] and result["telegram"]["ok"]
    urls = [c[0] for c in calls]
    assert "https://ntfy.example/home" in urls
    assert any("api.telegram.org/bottok/sendMessage" in u for u in urls)
    assert calls[0][1]["headers"]["Title"] == "Hestia test notification"


def test_notify_tool(client, monkeypatch):
    from hestia import notify
    from hestia.tools import build_registry
    from hestia.tools.registry import ProjectContext

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(
        notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp()
    )
    monkeypatch.setenv("NTFY_TOPIC", "home")

    ctx = ProjectContext(project_id=1, name="t", repo_url="", local_path=Path("."))
    tool = build_registry().get("notify")
    out = tool.handler(ctx, {"title": "Deploy done", "message": "shipped"})
    assert out["ntfy"]["ok"]
    assert calls == ["https://ntfy.sh/home"]


def test_inbox_poll_and_read(client, monkeypatch):
    from hestia import overview

    project = _mk_project(client)
    prs = [
        {
            "number": 1,
            "title": "Add caching",
            "user": "eve",
            "url": "https://github.com/a/b/pull/1",
        }
    ]
    runs = [
        {
            "id": 11,
            "name": "CI",
            "conclusion": "failure",
            "url": "https://github.com/a/b/runs/11",
        },
        {"id": 12, "name": "CI", "conclusion": "success", "url": "x"},
    ]

    def fake_github_list(repo_url, kind, state="open", limit=30):
        items = prs if kind == "prs" else runs if kind == "runs" else []
        return {"available": True, "repo": "a/b", "items": items}

    monkeypatch.setattr(overview, "github_list_for_url", fake_github_list)
    monkeypatch.setattr(overview, "repo_slug", lambda url: "a/b")

    # first poll is a baseline: items arrive already read
    assert client.post("/api/inbox/poll").json()["added"] == 2
    data = client.get("/api/inbox").json()
    assert data["unread"] == 0
    assert {i["kind"] for i in data["items"]} == {"pr", "run"}

    # a new PR shows up unread
    prs.append(
        {"number": 2, "title": "Fix bug", "user": "bob", "url": "https://github.com/a/b/pull/2"}
    )
    assert client.post("/api/inbox/poll").json()["added"] == 1
    data = client.get("/api/inbox", params={"unread": "true"}).json()
    assert data["unread"] == 1
    assert data["items"][0]["title"] == "#2 Fix bug"

    assert client.post("/api/inbox/read-all").json() == {"ok": True}
    assert client.get("/api/inbox").json()["unread"] == 0


def test_inbox_notifies_new_items(client, monkeypatch):
    from hestia import notify, overview

    _mk_project(client)
    prs = [{"number": 1, "title": "one", "user": "eve", "url": "u1"}]

    def fake_github_list(repo_url, kind, state="open", limit=30):
        return {"available": True, "repo": "a/b", "items": prs if kind == "prs" else []}

    monkeypatch.setattr(overview, "github_list_for_url", fake_github_list)
    monkeypatch.setattr(overview, "repo_slug", lambda url: "a/b")
    monkeypatch.setenv("NTFY_TOPIC", "home")

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp())

    assert client.post("/api/inbox/poll").json()["added"] == 1
    assert calls == []  # the first poll is a silent baseline

    prs.append({"number": 2, "title": "two", "user": "bob", "url": "u2"})
    assert client.post("/api/inbox/poll").json()["added"] == 1
    assert calls == ["https://ntfy.sh/home"]


def test_inbox_poll_emits_ci_event(client, monkeypatch):
    from sqlmodel import Session as SqlSession, select

    from hestia import overview
    from hestia.registry.db import engine
    from hestia.registry.models import Event

    project = _mk_project(client)
    runs = [{"id": 99, "name": "CI", "conclusion": "failure", "url": "u"}]
    monkeypatch.setattr(
        overview,
        "github_list_for_url",
        lambda repo_url, kind, state="open", limit=30: {
            "available": True,
            "repo": "a/b",
            "items": runs if kind == "runs" else [],
        },
    )
    monkeypatch.setattr(overview, "repo_slug", lambda url: "a/b")

    client.post("/api/inbox/poll")  # baseline
    runs.append({"id": 100, "name": "CI", "conclusion": "failure", "url": "u2"})
    client.post("/api/inbox/poll")

    with SqlSession(engine()) as db:
        rows = db.exec(
            select(Event).where(
                Event.project_id == project["id"], Event.kind == "ci_failure"
            )
        ).all()
        assert any(e.key == "run:100" for e in rows)
