"""Async HTTP client for the decision engine (`POST /v1/systemone`).

Never raises: transport/HTTP/decode failures return None so the agent loop is
never broken or stalled by the evaluator. Retries only on 429/5xx.
"""

from __future__ import annotations

import asyncio
import time

import httpx

MAX_ATTEMPTS = 4
REQUEST_TIMEOUT = 5.0


async def ask(
    base_url: str,
    state: dict,
    questions: dict,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> dict | None:
    url = f"{base_url.rstrip('/')}/v1/systemone"
    body: dict = {"state": state, "questions": questions}
    if model:
        body["model"] = model
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(url, json=body, headers=headers)
            except Exception:
                return None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < MAX_ATTEMPTS:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                return None
            if response.status_code >= 400:
                return None
            try:
                data = response.json()
            except Exception:
                return None
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                return None
            return data
    return None


def ask_sync(
    base_url: str,
    state: dict,
    questions: dict,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> dict | None:
    """Blocking variant for sync tool handlers; same never-raises contract."""
    url = f"{base_url.rstrip('/')}/v1/systemone"
    body: dict = {"state": state, "questions": questions}
    if model:
        body["model"] = model
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = httpx.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
        except Exception:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(0.5 * 2**attempt)
                continue
            return None
        if response.status_code >= 400:
            return None
        try:
            data = response.json()
        except Exception:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            return None
        return data
    return None
