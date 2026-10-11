"""Agent loop test against a fake OpenAI-compatible provider."""

import json

import pytest

from hestia.agent import loop as agent_loop
from hestia.providers.base import OpenAIClient
from hestia.tools import build_registry
from hestia.tools.registry import ProjectContext


class FakeClient(OpenAIClient):
    """Scripted provider: replies with tool calls first, then a text answer."""

    def __init__(self, script):
        super().__init__("http://fake", None, "fake")
        self.script = list(script)
        self.calls = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append(messages)
        reply = self.script.pop(0) if self.script else {"content": "done"}
        chunks = []
        if reply.get("reasoning"):
            chunks.append({"choices": [{"delta": {"reasoning_content": reply["reasoning"]}}]})
        if reply.get("tool_calls"):
            for i, tc in enumerate(reply["tool_calls"]):
                chunks.append({"choices": [{"delta": {"tool_calls": [dict(index=i, id=tc["id"], function={"name": tc["name"], "arguments": ""})]}}]})
                chunks.append({"choices": [{"delta": {"tool_calls": [dict(index=i, function={"arguments": tc["arguments"]})]}}]})
        text = reply.get("content", "")
        for word in text.split(" "):
            chunks.append({"choices": [{"delta": {"content": word + " "}}]})
        if reply.get("usage"):
            chunks.append({"choices": [], "usage": reply["usage"]})
        for chunk in chunks:
            yield chunk


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Instructions\nUse sqlite.\n")
    return ProjectContext(project_id=1, name="t", repo_url="https://github.com/a/b", local_path=tmp_path)


@pytest.mark.asyncio
async def test_tool_call_loop(repo):
    client = FakeClient([
        {"tool_calls": [
            {"id": "call_1", "name": "read_agents_md", "arguments": "{}"},
            {"id": "call_2", "name": "memory_create", "arguments": json.dumps({
                "type": "decision", "title": "D", "statement": "S", "tags": ["x"]})},
        ]},
        {"content": "Based on AGENTS.md, the project uses sqlite."},
    ])
    registry = build_registry()
    events = [e async for e in agent_loop.run_turn(repo, client, registry, [{"role": "user", "content": "hi"}])]

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert [t["name"] for t in tool_results] == ["read_agents_md", "memory_create"]
    assert all(t["ok"] for t in tool_results)
    assert events[-1]["type"] == "message"
    assert "sqlite" in events[-1]["content"]
    # tokens stream before the final message of each turn
    token_events = [e for e in events if e["type"] == "token"]
    assert token_events and "".join(t["text"] for t in token_events).strip().endswith("sqlite.")


@pytest.mark.asyncio
async def test_reasoning_content_is_echoed_back(repo):
    client = FakeClient([
        {"reasoning": "I should read it first",
         "tool_calls": [{"id": "c1", "name": "read_agents_md", "arguments": "{}"}]},
        {"content": "done"},
    ])
    registry = build_registry()
    events = [e async for e in agent_loop.run_turn(repo, client, registry, [{"role": "user", "content": "hi"}])]
    thinking = [e for e in events if e["type"] == "thinking"]
    assert thinking and thinking[0]["text"] == "I should read it first"
    # The provider requires reasoning_content echoed on the assistant message.
    second_call = client.calls[1]
    assistant = [m for m in second_call if m.get("role") == "assistant"][-1]
    assert assistant["reasoning_content"] == "I should read it first"


@pytest.mark.asyncio
async def test_usage_event(repo):
    client = FakeClient([
        {"content": "hi", "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    ])
    registry = build_registry()
    events = [e async for e in agent_loop.run_turn(repo, client, registry, [{"role": "user", "content": "hi"}])]

    usage_events = [e for e in events if e["type"] == "usage"]
    assert usage_events[0]["usage"]["prompt_tokens"] == 7
    assert usage_events[0]["usage"]["completion_tokens"] == 3


@pytest.mark.asyncio
async def test_agent_pause_ends_turn(repo):
    from hestia.tools.registry import Registry, Tool, schema

    class PausingClient(FakeClient):
        def __init__(self):
            super().__init__([{"tool_calls": [{"id": "c1", "name": "ask", "arguments": "{}"}]}])

    registry = Registry()

    def ask(ctx, args):
        raise agent_loop.AgentPause({"id": 7, "question": "Which DB?", "options": ["sqlite"]})

    registry.register(Tool(name="ask", description="", parameters=schema({}, []), handler=ask))
    events = [
        e
        async for e in agent_loop.run_turn(
            repo, PausingClient(), registry, [{"role": "user", "content": "hi"}]
        )
    ]
    assert events[-1]["type"] == "question"
    assert events[-1]["id"] == 7 and events[-1]["question"] == "Which DB?"
    # the turn ended: no follow-up model message after the pause
    assert [e["type"] for e in events].count("message") == 1
