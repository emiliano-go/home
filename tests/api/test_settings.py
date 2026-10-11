"""Settings, assistant preferences, and token budgets."""

from tests.api.conftest import _mk_project, _mk_provider


def test_settings_roundtrip(client, monkeypatch):
    from hestia import settings

    data = client.get("/api/settings").json()
    assert data["timezone"] == "UTC" and data["briefing_enabled"] == "0"

    updated = client.put(
        "/api/settings",
        json={
            "user_name": "Emi",
            "timezone": "Europe/Rome",
            "briefing_enabled": "1",
            "briefing_time": "07:30",
        },
    ).json()
    assert updated["user_name"] == "Emi"
    assert updated["timezone"] == "Europe/Rome"

    assert client.put("/api/settings", json={"timezone": "Not/AZone"}).status_code == 400
    assert client.put("/api/settings", json={"briefing_time": "25:00"}).status_code == 400
    assert client.put("/api/settings", json={"nope": "x"}).status_code == 400

    monkeypatch.setenv("HESTIA_ORIGIN", "https://home.example")
    assert settings.notification_url("/g/reminders") == "https://home.example/#/g/reminders"
    monkeypatch.delenv("HESTIA_ORIGIN")
    assert settings.notification_url("/g/reminders") is None


def test_prompt_includes_context(client, monkeypatch):
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.put(
        "/api/settings",
        json={"user_name": "Emi", "timezone": "Europe/Rome", "instructions": "Be terse."},
    )
    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def stream_chat(self, messages, tools=None):
            seen["system"] = messages[0]["content"]
            yield {"choices": [{"delta": {"content": "ok"}}]}

    monkeypatch.setattr(chat_router, "provider_client", FakeClient)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hi", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert "Current time:" in seen["system"]
    assert "Emi" in seen["system"]
    assert "Be terse." in seen["system"]


def test_preferences_crud(client):
    assert client.get("/api/settings/preferences").json() == {"preferences": []}
    assert client.post("/api/settings/preferences", json={"text": ""}).status_code == 400

    added = client.post(
        "/api/settings/preferences", json={"text": "Never use em dashes."}
    ).json()
    assert added["preferences"] == ["Never use em dashes."]

    again = client.post(
        "/api/settings/preferences", json={"text": "Never use em dashes."}
    ).json()
    assert again["preferences"] == ["Never use em dashes."]

    client.post("/api/settings/preferences", json={"text": "Be concise."})
    assert client.delete("/api/settings/preferences/0").json()["preferences"] == [
        "Be concise."
    ]
    assert client.delete("/api/settings/preferences/9").json()["preferences"] == [
        "Be concise."
    ]


def test_preferences_in_prompt(client, monkeypatch):
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.post("/api/settings/preferences", json={"text": "Never use em dashes."})
    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def stream_chat(self, messages, tools=None):
            seen["system"] = messages[0]["content"]
            yield {"choices": [{"delta": {"content": "ok"}}]}

    monkeypatch.setattr(chat_router, "provider_client", FakeClient)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hi", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert "USER CONTEXT" in seen["system"]
    assert "Never use em dashes." in seen["system"]


def test_preference_edit(client):
    client.post("/api/settings/preferences", json={"text": "one"})
    client.post("/api/settings/preferences", json={"text": "two"})
    updated = client.put("/api/settings/preferences/1", json={"text": "TWO"}).json()
    assert updated["preferences"] == ["one", "TWO"]
    assert client.put("/api/settings/preferences/1", json={"text": "  "}).status_code == 400


def test_token_budget(client):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import scheduler
    from hestia.registry.db import engine
    from hestia.registry.models import Usage

    project = _mk_project(client)
    pid = project["id"]
    with SqlSession(engine()) as db:
        db.add(Usage(project_id=pid, action="chat", prompt_tokens=600, completion_tokens=400))
        db.commit()

    data = client.get(f"/api/projects/{pid}/usage").json()
    assert data["month"]["tokens"] == 1000
    assert data["budget"] == {
        "budget": None,
        "enforced": False,
        "used": 1000,
        "percent": None,
        "over": False,
    }

    updated = client.put(
        f"/api/projects/{pid}", json={"token_budget": 800, "budget_enforced": True}
    ).json()
    assert updated["token_budget"] == 800 and updated["budget_enforced"] is True
    assert client.put(f"/api/projects/{pid}", json={"token_budget": "abc"}).status_code == 400

    data = client.get(f"/api/projects/{pid}/usage").json()
    assert data["budget"]["over"] is True and data["budget"]["percent"] == 125

    sched = client.post(
        f"/api/projects/{pid}/schedules",
        json={"action": "github-scan", "instruction": "digest"},
    ).json()
    result = asyncio.run(scheduler.run_schedule(sched["id"]))
    assert result["last_status"] == "skipped: budget"


def test_browser_settings(client):
    data = client.get("/api/settings").json()
    assert data["browser_enabled"] == "1"
    assert data["browser_cdp_url"] == ""

    updated = client.put(
        "/api/settings",
        json={"browser_enabled": "0", "browser_cdp_url": "http://localhost:9222"},
    ).json()
    assert updated["browser_enabled"] == "0"
    assert updated["browser_cdp_url"] == "http://localhost:9222"
