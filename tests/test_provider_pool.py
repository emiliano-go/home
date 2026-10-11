"""Provider key pools and rotation."""

import json
from types import SimpleNamespace

import pytest

from hestia.providers import pool
from hestia.providers.base import OpenAIClient


def _provider(**kwargs):
    base = {"keys": "[]", "api_key": None, "api_key_env": "", "key_state": "{}"}
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_keys_of_merges_sources(monkeypatch):
    monkeypatch.setenv("MY_KEY", "envkey")
    provider = _provider(api_key="stored", keys='["k2", "k3"]', api_key_env="MY_KEY")
    assert pool.keys_of(provider) == ["stored", "k2", "k3", "envkey"]


def test_active_skips_suspended_and_revoked():
    state = {"suspended": {pool.hash_key("a"): 9_999_999_999}, "revoked": [pool.hash_key("b")]}
    provider = _provider(keys='["a", "b", "c"]', key_state=json.dumps(state))
    assert pool.active(provider) == "c"


def test_note_failure_suspends_and_revokes():
    provider = _provider(keys='["a", "b"]')
    pool.note_failure(provider, "a", 429, cooldown=120)
    assert pool.hash_key("a") in json.loads(provider.key_state)["suspended"]
    pool.note_failure(provider, "b", 401)
    assert pool.hash_key("b") in json.loads(provider.key_state)["revoked"]


def test_active_all_unusable_returns_first():
    provider = _provider(keys='["a"]', key_state=json.dumps({"revoked": [pool.hash_key("a")]}))
    assert pool.active(provider) == "a"


def test_should_rotate_mapping():
    assert pool.should_rotate(429) == "suspend"
    assert pool.should_rotate(402) == "suspend"
    assert pool.should_rotate(401) == "revoke"
    assert pool.should_rotate(403) == "revoke"
    assert pool.should_rotate(500) is None


class _FakeResponse:
    def __init__(self, status, lines):
        self.status_code = status
        self._lines = lines
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aread(self):
        return b"rate limited"

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, headers=None, json=None):
        auth = (headers or {}).get("Authorization")
        self.calls.append(auth)
        if auth == "Bearer bad":
            return _FakeResponse(429, [])
        return _FakeResponse(200, ['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"])


@pytest.mark.asyncio
async def test_client_rotates_on_429(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr("hestia.providers.base.httpx.AsyncClient", _FakeClient)
    failures = []
    client = OpenAIClient(
        "http://x",
        "bad",
        "m",
        keys=["bad", "good"],
        on_key_failure=lambda key, status, cooldown: failures.append((key, status)),
    )
    chunks = [chunk async for chunk in client.stream_chat([{"role": "user", "content": "hi"}])]
    assert failures and failures[0] == ("bad", 429)
    assert chunks and "hi" in str(chunks[0])
    assert _FakeClient.calls == ["Bearer bad", "Bearer good"]


def test_resolve_small_model_falls_back():
    from hestia.providers.base import resolve_small_model

    assert resolve_small_model(SimpleNamespace(small_model="", model="m")) == "m"
    assert resolve_small_model(SimpleNamespace(small_model="mini", model="m")) == "mini"
