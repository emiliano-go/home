"""Reminders, briefings, watches, and web fetch."""

from pathlib import Path

import pytest

from tests.api.conftest import _mk_project, _mk_provider


def test_reminder_crud_and_fire(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from sqlmodel import Session as SqlSession

    from hestia import notify, reminders
    from hestia.registry.db import engine

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp())
    monkeypatch.setenv("NTFY_TOPIC", "home")

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    created = client.post(
        "/api/reminders",
        json={"text": "water plants", "due_at": past, "recurrence": "daily"},
    ).json()
    assert created["status"] == "pending" and created["recurrence"] == "daily"
    assert client.post(
        "/api/reminders", json={"text": "x", "due_at": "not-a-date"}
    ).status_code == 400
    assert client.post(
        "/api/reminders", json={"text": "", "due_at": future}
    ).status_code == 400

    with SqlSession(engine()) as db:
        assert reminders.fire_due(db) == 1
    assert len(calls) == 1
    items = client.get("/api/reminders").json()
    assert len(items) == 1 and items[0]["status"] == "pending"

    assert client.put(
        f"/api/reminders/{created['id']}", json={"snooze_minutes": 10}
    ).status_code == 200
    assert client.put(
        f"/api/reminders/{created['id']}", json={"status": "done"}
    ).json()["status"] == "done"
    assert client.get("/api/reminders").json() == []
    assert len(client.get("/api/reminders", params={"include_done": "true"}).json()) == 1
    assert client.delete(f"/api/reminders/{created['id']}").status_code == 204


def test_remind_me_tool(client):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.tools import reminders as reminder_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    ctx = ProjectContext(
        project_id=project["id"],
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    with SqlSession(engine()) as db:
        tools = {t.name: t for t in reminder_tools.make_tools(db)}
        created = tools["remind_me"].handler(
            ctx, {"text": "call mom", "due_at": "2030-01-01T09:00:00+00:00"}
        )
        assert created["project_id"] == project["id"]
        assert tools["reminder_list"].handler(ctx, {})[0]["text"] == "call mom"
        tools["reminder_cancel"].handler(ctx, {"id": created["id"]})
        assert tools["reminder_list"].handler(ctx, {}) == []


def test_briefing_digest_and_once_per_day(client, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from sqlmodel import Session as SqlSession

    from hestia import notify, scheduler
    from hestia.registry.db import engine

    project = _mk_project(client)
    client.post(
        f"/api/projects/{project['id']}/tasks", json={"title": "ship it", "status": "todo"}
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    client.post("/api/reminders", json={"text": "ping", "due_at": past})
    client.put("/api/settings", json={"briefing_enabled": "1", "briefing_time": "00:00"})

    class FakeResp:
        status_code = 200
        text = "ok"

    messages = []
    monkeypatch.setattr(
        notify.httpx,
        "post",
        lambda url, **kw: messages.append(kw.get("content", b"").decode()) or FakeResp(),
    )
    monkeypatch.setenv("NTFY_TOPIC", "home")

    with SqlSession(engine()) as db:
        digest = scheduler._briefing_digest(db)
        assert "ship it" in digest and "ping" in digest
        asyncio.run(scheduler._maybe_send_briefing(db))
        asyncio.run(scheduler._maybe_send_briefing(db))  # guarded to once per day

    assert len(messages) == 1
    assert "ship it" in messages[0]


def test_watch_page_change_and_appear(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import notify, watchers
    from hestia.registry.db import engine

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(
        notify.httpx, "post", lambda url, **kw: calls.append(kw.get("content", b"").decode()) or FakeResp()
    )
    monkeypatch.setenv("NTFY_TOPIC", "home")

    page = {"text": "alpha beta"}
    monkeypatch.setattr(
        watchers.webfetch,
        "fetch",
        lambda url: {"text": page["text"], "content_type": "text/html", "url": url, "bytes": 10},
    )

    with SqlSession(engine()) as db:
        watch = watchers.create(db, "page", url="https://example.com", interval_minutes=30)
        asyncio.run(watchers.check(db, watch))  # baseline, silent
        assert calls == []
        page["text"] = "alpha beta gamma"
        asyncio.run(watchers.check(db, watch))
        assert len(calls) == 1
        assert watch.last_result == "changed"

        appear = watchers.create(
            db,
            "page",
            url="https://example.com/tickets",
            notify_on="appear",
            condition="In stock",
        )
        page["text"] = "Sold out"
        asyncio.run(watchers.check(db, appear))  # baseline
        page["text"] = "Sold out still"
        asyncio.run(watchers.check(db, appear))  # changed but no match
        assert len(calls) == 1
        page["text"] = "In stock now"
        asyncio.run(watchers.check(db, appear))
        assert len(calls) == 2
        assert appear.status == "done"


def test_watch_feed_new_items(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import notify, watchers
    from hestia.registry.db import engine

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(
        notify.httpx, "post", lambda url, **kw: calls.append(kw.get("content", b"").decode()) or FakeResp()
    )
    monkeypatch.setenv("NTFY_TOPIC", "home")

    rss = (
        "<rss><channel><item><title>One</title><guid>1</guid>"
        "<link>https://x/1</link></item></channel></rss>"
    )
    state = {"xml": rss}
    monkeypatch.setattr(
        watchers.webfetch,
        "fetch",
        lambda url: {"text": state["xml"], "content_type": "application/rss+xml", "url": url, "bytes": 10},
    )

    with SqlSession(engine()) as db:
        watch = watchers.create(db, "feed", url="https://x/feed")
        asyncio.run(watchers.check(db, watch))  # baseline
        assert calls == []
        state["xml"] = rss.replace(
            "</channel>",
            "<item><title>Two</title><guid>2</guid><link>https://x/2</link></item></channel>",
        )
        asyncio.run(watchers.check(db, watch))
        assert len(calls) == 1
        assert "Two" in calls[0]


def test_watch_condition(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import notify, watchers
    from hestia.agent import loop as agent_loop
    from hestia.registry.db import engine

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.post("/api/agents", json={"name": "chat", "provider_id": provider["id"]})

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        yield {"type": "message", "content": "MET\nThe v2 release is published.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp())
    monkeypatch.setenv("NTFY_TOPIC", "home")

    with SqlSession(engine()) as db:
        watch = watchers.create(
            db, "condition", condition="Is v2 published?", url="https://example.com"
        )
        asyncio.run(watchers.check(db, watch))
        assert watch.status == "done"
    assert len(calls) == 1


def test_watches_api(client):
    assert client.get("/api/watches").json() == []
    assert client.post("/api/watches", json={"kind": "page"}).status_code == 400
    created = client.post(
        "/api/watches",
        json={"kind": "page", "url": "https://example.com", "interval_minutes": 5},
    ).json()
    assert created["interval_minutes"] == 30
    assert client.put(
        f"/api/watches/{created['id']}", json={"status": "paused"}
    ).json()["status"] == "paused"
    assert client.delete(f"/api/watches/{created['id']}").status_code == 204
    assert client.put("/api/watches/999", json={"status": "paused"}).status_code == 404


def test_web_fetch_ssrf_guard(client):
    from hestia import webfetch

    for blocked in (
        "http://127.0.0.1:8000/",
        "http://localhost:8080/",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(webfetch.FetchError):
            webfetch.fetch(blocked)


def test_web_fetch_html_to_text(monkeypatch):
    from hestia import webfetch

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        content = (
            b"<html><head><style>x</style></head><body><h1>Hi</h1>"
            b"<script>bad()</script><p>There</p></body></html>"
        )
        encoding = "utf-8"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(webfetch.httpx, "Client", FakeClient)
    monkeypatch.setattr(webfetch, "_validate", lambda url: url)
    out = webfetch.fetch("https://example.com")
    assert "Hi" in out["text"] and "There" in out["text"]
    assert "bad()" not in out["text"]
    assert out["content_type"] == "text/html"
