"""OpenAI-compatible chat-completions client (async, streaming, tool calling)."""

import os
import secrets
from typing import Any, AsyncIterator

import httpx

from hestia.providers.pool import cooldown_seconds

USER_AGENT = "hestia-agent/1.0"

# Accepted reasoning_effort values. Some Go models reject "medium" (e.g. GLM);
# "none" disables thinking entirely on models that allow it.
REASONING_EFFORTS = ("none", "low", "medium", "high", "max")


class ProviderError(RuntimeError):
    pass


class OpenAIClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 120.0,
        session: str | None = None,
        reasoning_effort: str | None = None,
        keys: list[str] | None = None,
        on_key_failure=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # none | low | medium | high | max; omitted from the payload when unset
        self.reasoning_effort = reasoning_effort or None
        # OpenCode Go wants a stable per-conversation session id for routing;
        # callers pass the chat/session id when they have one.
        self.session = session or secrets.token_urlsafe(12)
        # Rotation pool: on 429/402/401/403 try the next key. on_key_failure is
        # called with (key, status, cooldown_seconds) so the caller can persist
        # the suspension/revocation on the provider row.
        self.keys = keys
        self.on_key_failure = on_key_failure

    def _headers(self, key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if "opencode.ai" in self.base_url:
            headers["x-opencode-session"] = self.session
        return headers

    def _payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw SSE chunks from /chat/completions, rotating keys on failure."""
        payload = self._payload(messages, tools)
        keys = self.keys or ([self.api_key] if self.api_key else [None])
        last_error: ProviderError | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for index, key in enumerate(keys):
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    headers=self._headers(key),
                    json=payload,
                ) as resp:
                    if resp.status_code == 200:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line.removeprefix("data:").strip()
                            if data == "[DONE]":
                                return
                            import json

                            yield json.loads(data)
                        return
                    body = await resp.aread()
                    error = ProviderError(
                        f"{resp.status_code}: {body.decode('utf-8', 'replace')[:500]}"
                    )
                    if resp.status_code in (429, 402, 401, 403) and index + 1 < len(keys):
                        if self.on_key_failure is not None:
                            cooldown = cooldown_seconds(resp.headers)
                            try:
                                self.on_key_failure(key, resp.status_code, cooldown)
                            except Exception:  # noqa: BLE001
                                pass
                        last_error = error
                        continue
                    raise error
        if last_error is not None:
            raise last_error

    async def test_connection(self) -> dict[str, Any]:
        """Cheap liveness check: 1-token completion."""
        chunks = []
        async for chunk in self.stream_chat(
            [{"role": "user", "content": "ping"}], tools=None
        ):
            chunks.append(chunk)
            break
        return chunks[0] if chunks else {}


def resolve_api_key(provider) -> str | None:
    """The provider's currently active key (pool-aware), else its env var.

    Accepts a Provider or a bare env var name (backwards compatible).
    """
    if isinstance(provider, str):
        return os.environ.get(provider) or None
    from hestia.providers import pool

    return pool.active(provider)


def provider_client(provider, model: str, db=None, **kwargs) -> OpenAIClient:
    """Build a client with the provider's key pool and failure reporting."""
    from hestia.providers import pool

    keys = pool.keys_of(provider)

    def on_key_failure(key, status, cooldown):
        pool.note_failure(provider, key, status, cooldown)
        if db is not None:
            try:
                db.add(provider)
                db.commit()
            except Exception:  # noqa: BLE001
                pass

    return OpenAIClient(
        provider.base_url,
        pool.active(provider),
        model,
        keys=keys or None,
        on_key_failure=on_key_failure,
        **kwargs,
    )


def resolve_model(agent, provider) -> str:
    """The agent's model override when set, else the provider's model."""
    return getattr(agent, "model", None) or provider.model


def resolve_small_model(provider) -> str:
    """Cheap model for titles/summaries/distillation; falls back to the main model."""
    return getattr(provider, "small_model", "") or provider.model


async def list_models(base_url: str, api_key: str | None) -> list[str]:
    """Fetch model ids from an OpenAI-compatible /v1/models endpoint."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/v1/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    ids = {
        m.get("id")
        for m in (data.get("data") or [])
        if isinstance(m, dict) and m.get("id")
    }
    return sorted(ids)
