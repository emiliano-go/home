"""Tool-calling agent loop with SSE event streaming.

Yields event dicts:
    {"type": "token", "text": ...}
    {"type": "thinking", "text": ...}
    {"type": "tool_call", "name": ..., "arguments": ...}
    {"type": "tool_result", "name": ..., "ok": bool, "preview": str}
    {"type": "message", "content": ..., "tool_calls": [...]}
    {"type": "question", ...} (from AgentPause tools)
    {"type": "error" | "stopped" | "timed_out", "message": ...}

Tools run off the event loop (worker thread) so streaming stays responsive.
Malformed tool arguments become failed tool results instead of killing the
turn, and repeated identical calls are flagged/aborted as a loop.
"""

import asyncio
import json
import os
import time
from typing import Any, AsyncIterator

from hestia.providers.base import OpenAIClient
from hestia.tools import plan as plan_tools
from hestia.tools.registry import ProjectContext, Registry

RUN_TIMEOUT = float(os.environ.get("HESTIA_RUN_TIMEOUT", "1800"))
LOOP_REPEAT_LIMIT = 4  # consecutive identical calls -> abort
LOOP_FAIL_LIMIT = 3  # identical failing calls -> abort


class AgentPause(Exception):
    """Raised by a tool to end the turn and wait for the user (e.g. ask_user).

    ``payload`` is forwarded as a ``question`` event by ``run_turn``.
    """

    def __init__(self, payload: dict[str, Any]):
        super().__init__("agent paused")
        self.payload = payload


def _with_note(result: Any, note: str) -> Any:
    if isinstance(result, dict):
        return {**result, "_note": note}
    if isinstance(result, list):
        return result + [{"_note": note}]
    return f"{result}\n\n({note})"


async def run_turn(
    ctx: ProjectContext,
    client: OpenAIClient,
    registry: Registry,
    messages: list[dict[str, Any]],
    max_turns: int | None = None,
    run=None,
    timeout: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run until the model stops calling tools.

    ``max_turns`` bounds nested loops only (none by default). ``run`` is the
    RunManager run: it provides cancellation and step tracking. ``timeout``
    defaults to ``HESTIA_RUN_TIMEOUT``.
    """
    tools = registry.openai_schemas()
    turns = 0
    deadline = time.monotonic() + (timeout if timeout is not None else RUN_TIMEOUT)
    seen: dict[tuple, int] = {}
    failures: dict[tuple, int] = {}
    last_key: tuple | None = None
    streak = 0
    try:
        while max_turns is None or turns < max_turns:
            if run is not None and run.cancelled:
                yield {"type": "stopped", "message": "stopped by request"}
                return
            if time.monotonic() > deadline:
                limit = int(timeout if timeout is not None else RUN_TIMEOUT)
                yield {"type": "timed_out", "message": f"run exceeded {limit}s"}
                return
            turns += 1
            if run is not None:
                run.steps = turns

            turn: dict[str, Any] = {}
            async for event in _stream_turn(client, messages, tools):
                if event["type"] == "_turn":
                    turn = event
                else:
                    yield event
            content = turn.get("content", "")
            tool_calls = turn.get("tool_calls", [])
            reasoning = turn.get("reasoning", "")
            usage = turn.get("usage")
            if usage:
                yield {"type": "usage", "usage": usage}
            yield {"type": "message", "content": content, "tool_calls": tool_calls}
            if not tool_calls:
                return
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            }
            # Thinking models (DeepSeek/MiMo/Kimi on OpenCode Go) require the
            # reasoning to be echoed back on assistant messages, or the next
            # request is rejected with "reasoning_content must be passed back".
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            messages.append(assistant_msg)
            for call in tool_calls:
                name = call["function"]["name"]
                raw = call["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw)
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except ValueError as exc:
                    # one bad call must not kill the turn; let the model retry
                    yield {"type": "tool_call", "id": call["id"], "name": name, "arguments": {}}
                    result = (
                        f"invalid tool arguments: {exc}. "
                        f"Call {name} again with a valid JSON object."
                    )
                    yield {
                        "type": "tool_result",
                        "id": call["id"],
                        "name": name,
                        "ok": False,
                        "preview": result,
                    }
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": result}
                    )
                    continue

                if run is not None and run.cancelled:
                    yield {"type": "stopped", "message": "stopped by request"}
                    return

                yield {"type": "tool_call", "id": call["id"], "name": name, "arguments": args}

                key = (name, json.dumps(args, sort_keys=True, default=str)[:500])
                seen[key] = seen.get(key, 0) + 1
                if key == last_key:
                    streak += 1
                else:
                    last_key, streak = key, 1

                ctx.tool_call_id = call["id"]
                try:
                    ok, result = await asyncio.to_thread(_execute, registry, ctx, name, args)
                except AgentPause as pause:
                    yield {"type": "question", **pause.payload}
                    return
                finally:
                    ctx.tool_call_id = None

                if not ok:
                    failures[key] = failures.get(key, 0) + 1
                elif seen[key] >= 2:
                    result = _with_note(
                        result, "you already ran this exact call; the result is unchanged"
                    )

                preview = json.dumps(result, default=str)[:2000]
                yield {
                    "type": "tool_result",
                    "id": call["id"],
                    "name": name,
                    "ok": ok,
                    "preview": preview,
                }
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, default=str)[:20_000],
                })

                if streak >= LOOP_REPEAT_LIMIT or failures.get(key, 0) >= LOOP_FAIL_LIMIT:
                    yield {
                        "type": "error",
                        "message": (
                            f"loop detected: {name} repeated without progress; stopping. "
                            "Try a different approach or stop and guide the agent."
                        ),
                    }
                    return
        yield {"type": "error", "message": f"stopped after {max_turns} tool-call turns"}
    except Exception as e:
        yield {"type": "error", "message": str(e)[:1000]}


async def _stream_turn(
    client: OpenAIClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Stream one provider turn: token events, then a final ``_turn`` dict."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] | None = None
    async for chunk in client.stream_chat(messages, tools=tools):
        if chunk.get("usage"):
            usage = chunk["usage"]
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
            yield {"type": "token", "text": delta["content"]}
        # reasoning models stream thinking under different keys
        for key in ("reasoning_content", "reasoning", "thinking"):
            reasoning = delta.get(key)
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
                yield {"type": "thinking", "text": reasoning}
                break
        for dtc in delta.get("tool_calls") or []:
            idx = dtc.get("index", 0)
            call = calls.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if dtc.get("id"):
                call["id"] = dtc["id"]
            fn = dtc.get("function") or {}
            if fn.get("name"):
                call["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                call["function"]["arguments"] += fn["arguments"]
    yield {
        "type": "_turn",
        "content": "".join(content_parts),
        "reasoning": "".join(reasoning_parts),
        "tool_calls": [calls[i] for i in sorted(calls)],
        "usage": usage,
    }


def _execute(registry: Registry, ctx: ProjectContext, name: str, args: dict[str, Any]) -> tuple[bool, Any]:
    tool = registry.get(name)
    if tool is None:
        return False, f"unknown tool: {name}"
    blocked = plan_tools.check_gate(ctx, name, registry)
    if blocked:
        return False, blocked
    try:
        result = tool.handler(ctx, args)
    except AgentPause:
        raise  # ends the turn; handled by run_turn
    except PermissionError as e:
        return False, f"blocked by sandbox: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    plan_tools.after_write(ctx, name, True, registry)
    return True, result
