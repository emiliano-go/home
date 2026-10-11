"""Providers, models, and action defaults."""

from tests.api.conftest import _mk_provider


def test_opencode_preset(client):
    presets = client.get("/api/providers/presets").json()
    assert "opencode" in presets
    assert presets["opencode"]["name"] == "OpenCode Go"
    assert presets["opencode"]["base_url"] == "https://opencode.ai/zen/go"


def test_provider_stored_key(client, monkeypatch):
    from hestia.providers import base as provider_base
    from hestia.registry.models import Provider

    p = client.post(
        "/api/providers",
        json={"name": "zen", "base_url": "https://opencode.ai/zen", "api_key": "sk-x"},
    ).json()
    assert p["has_key"] is True
    assert "api_key" not in p

    listed = client.get("/api/providers").json()
    assert listed[0]["has_key"] is True
    assert "api_key" not in listed[0]

    prov = Provider(name="zen", base_url="https://x", api_key="stored", api_key_env="NOPE")
    assert provider_base.resolve_api_key(prov) == "stored"
    assert provider_base.resolve_api_key("NOPE") is None


def test_provider_models_endpoint(client, monkeypatch):
    async def fake_list_models(base_url, api_key):
        assert base_url == "https://opencode.ai/zen"
        assert api_key == "sk-x"
        return ["deepseek-v4.1-flash", "gpt-5.4-mini"]

    monkeypatch.setattr("hestia.routers.providers.list_models", fake_list_models)
    resp = client.post(
        "/api/providers/models",
        json={"base_url": "https://opencode.ai/zen", "api_key": "sk-x"},
    )
    assert resp.status_code == 200
    assert resp.json()["models"] == ["deepseek-v4.1-flash", "gpt-5.4-mini"]


def test_provider_models_crud(client):
    p = client.post(
        "/api/providers",
        json={"name": "multi", "base_url": "http://x", "api_key": "k", "models": ["a", "b"]},
    ).json()
    assert p["models"] == ["a", "b"]
    assert p["model"] == "a"  # default = first

    p2 = client.post(f"/api/providers/{p['id']}/models", json={"models": ["c", "a"]}).json()
    assert p2["models"] == ["a", "b", "c"]

    p3 = client.delete(f"/api/providers/{p['id']}/models/b").json()
    assert p3["models"] == ["a", "c"]

    # removing the default moves it to the first remaining
    p4 = client.delete(f"/api/providers/{p['id']}/models/a").json()
    assert p4["models"] == ["c"] and p4["model"] == "c"


def test_effective_provider_and_resolve_model(client):
    from hestia import actions
    from hestia.providers.base import resolve_model
    from hestia.registry.models import Provider

    class FakeAgent:
        model = "m2"

    prov = Provider(name="x", base_url="http://x", model="m1", models='["m1","m2"]')
    assert resolve_model(FakeAgent(), prov) == "m2"
    assert resolve_model(None, prov) == "m1"

    eff = actions.effective_provider(FakeAgent(), prov)
    assert eff.model == "m2"
    assert prov.model == "m1"  # original is untouched


def test_action_defaults_roundtrip(client):
    provider = _mk_provider(client)
    agent = client.post("/api/agents", json={
        "name": "default", "provider_id": provider["id"], "tools": ["repo"], "max_turns": 3,
    }).json()

    actions = client.get("/api/actions").json()
    assert next(a for a in actions if a["key"] == "chat")["agent_id"] is None
    assert all("description" in a for a in actions)

    assert client.put("/api/actions/chat", json={"agent_id": agent["id"]}).status_code == 200
    actions = client.get("/api/actions").json()
    assert next(a for a in actions if a["key"] == "chat")["agent_id"] == agent["id"]

    assert client.put("/api/actions/nope", json={"agent_id": None}).status_code == 404

    updated = client.put(
        f"/api/agents/{agent['id']}", json={"max_turns": 5, "tools": ["repo", "memory"]}
    ).json()
    assert updated["max_turns"] == 5
    assert updated["tools"] == "repo,memory"


def test_action_resolution_falls_back_to_chat(client):
    from sqlmodel import Session as SqlSession

    from hestia import actions as actions_mod
    from hestia.registry.db import engine

    provider = _mk_provider(client)
    solo = client.post("/api/agents", json={
        "name": "solo", "provider_id": provider["id"],
    }).json()
    client.put("/api/actions/chat", json={"agent_id": solo["id"]})

    with SqlSession(engine()) as db:
        assert actions_mod.resolve_action(db, "explore").id == solo["id"]

    client.put("/api/actions/chat", json={"agent_id": None})
    client.post("/api/agents", json={"name": "explore", "provider_id": provider["id"]})
    with SqlSession(engine()) as db:
        assert actions_mod.resolve_action(db, "explore").name == "explore"


def test_provider_key_pool(client):
    from tests.api.conftest import _mk_provider

    provider = _mk_provider(client)
    resp = client.put(f"/api/providers/{provider['id']}/keys", json={"keys": "k1, k2\nk3"})
    assert resp.status_code == 200
    assert resp.json()["key_count"] == 3
    assert client.get("/api/providers").json()[0]["key_count"] == 3


def test_provider_small_model(client):
    from tests.api.conftest import _mk_provider

    provider = _mk_provider(client)
    resp = client.patch(f"/api/providers/{provider['id']}", json={"small_model": "mini"})
    assert resp.status_code == 200
    assert resp.json()["small_model"] == "mini"
