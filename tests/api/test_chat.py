"""Chat streaming, questions/approvals, persistence, and /btw."""

from pathlib import Path

import pytest

from tests.api.conftest import _mk_project, _mk_provider


def test_chat_goal_action(client, monkeypatch):
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
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
        json={"message": "hi", "provider_id": provider["id"], "action": "goal"},
    )
    assert resp.status_code == 200
    assert "Goal mode" in seen["system"]


def test_ask_user_tool(client, monkeypatch):
    from sqlmodel import Session as SqlSession

    from hestia import notify
    from hestia import questions as questions_mod
    from hestia.agent.loop import AgentPause
    from hestia.registry.db import engine
    from hestia.registry.models import Session as ChatSession
    from hestia.tools import questions as question_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    monkeypatch.setenv("NTFY_TOPIC", "home")

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp())

    with SqlSession(engine()) as db:
        chat = ChatSession(project_id=project["id"], title="q")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        ctx = ProjectContext(
            project_id=project["id"],
            name=project["name"],
            repo_url=project["repo_url"],
            local_path=Path(project["local_path"]),
            session_id=chat.id,
        )
        tool = question_tools.make_tools(db)[0]
        with pytest.raises(AgentPause) as exc:
            tool.handler(ctx, {"question": "Which DB?", "options": ["sqlite", "postgres"]})
        assert exc.value.payload["question"] == "Which DB?"
        assert exc.value.payload["options"] == ["sqlite", "postgres"]
        rows = questions_mod.list_for_session(db, chat.id)
        assert len(rows) == 1 and rows[0].status == "open"

        bare = ProjectContext(project_id=1, name="x", repo_url="", local_path=Path("."))
        with pytest.raises(ValueError):
            tool.handler(bare, {"question": "x"})

    assert calls == ["https://ntfy.sh/home"]


def test_chat_question_flow(client, monkeypatch):
    from hestia.agent import loop as agent_loop
    from hestia.agent.loop import AgentPause

    project = _mk_project(client)
    provider = _mk_provider(client)
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            try:
                registry.get("ask_user").handler(
                    ctx, {"question": "Which database?", "options": ["sqlite", "postgres"]}
                )
            except AgentPause as pause:
                yield {"type": "question", **pause.payload}
                return
        yield {"type": "message", "content": "Understood.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "build it", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert '"event": "question"' in resp.text
    assert "Which database?" in resp.text

    sid = client.get(f"/api/projects/{project['id']}/sessions").json()[0]["id"]
    qs = client.get(f"/api/sessions/{sid}/questions").json()
    assert len(qs) == 1
    assert qs[0]["status"] == "open"
    assert qs[0]["options"] == ["sqlite", "postgres"]

    # the question is persisted in the transcript, so it survives a reload
    messages = client.get(f"/api/sessions/{sid}/messages").json()
    assert any(
        m["role"] == "assistant" and "Which database?" in m["content"] for m in messages
    )

    # answering with the next message marks it answered
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "postgres", "session_id": sid, "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    qs = client.get(f"/api/sessions/{sid}/questions").json()
    assert qs[0]["status"] == "answered" and qs[0]["answer"] == "postgres"

    # dismiss endpoint
    assert client.post(f"/api/questions/{qs[0]['id']}/dismiss").json()["status"] == "dismissed"
    assert client.post("/api/questions/999/dismiss").status_code == 404
    assert client.get("/api/sessions/999/questions").status_code == 404


def test_ask_approval_and_write_gate(client, monkeypatch):
    from sqlmodel import Session as SqlSession

    from hestia import questions as questions_mod
    from hestia.agent.loop import AgentPause
    from hestia.registry.db import engine
    from hestia.registry.models import Question
    from hestia.registry.models import Session as ChatSession
    from hestia.tools import gitwrites
    from hestia.tools import questions as question_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    pid = project["id"]
    client.put(f"/api/projects/{pid}/git-writes", json={"enabled": True})
    updated = client.put(
        f"/api/projects/{pid}", json={"require_write_approval": True}
    ).json()
    assert updated["require_write_approval"] is True

    ctx = ProjectContext(
        project_id=pid,
        name=project["name"],
        repo_url=project["repo_url"],
        local_path=Path(project["local_path"]),
    )
    with SqlSession(engine()) as db:
        chat = ChatSession(project_id=pid, title="approval")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        ctx.session_id = chat.id
        tools = {t.name: t for t in question_tools.make_tools(db)}
        with pytest.raises(AgentPause) as exc:
            tools["ask_approval"].handler(
                ctx, {"action": "git_push", "summary": "Push the feature branch"}
            )
        assert exc.value.payload["kind"] == "approval"
        assert exc.value.payload["options"] == ["approve", "deny"]

        # hard gate: no approved request yet
        with pytest.raises(PermissionError):
            gitwrites._push(ctx, {}, db)

        question = db.get(Question, exc.value.payload["id"])
        questions_mod.answer(db, question, "approve")

        monkeypatch.setattr(gitwrites, "_git", lambda *args, **kwargs: "pushed")
        result = gitwrites._push(ctx, {}, db)
        assert result["output"] == "pushed"


def test_chat_approval_event(client, monkeypatch):
    from hestia.agent import loop as agent_loop
    from hestia.agent.loop import AgentPause

    project = _mk_project(client)
    provider = _mk_provider(client)

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        try:
            registry.get("ask_approval").handler(
                ctx, {"action": "gh_open_pr", "summary": "Open the PR"}
            )
        except AgentPause as pause:
            yield {"type": "question", **pause.payload}
            return
        yield {"type": "message", "content": "no approval", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "ship it", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert '"kind": "approval"' in resp.text
    sid = client.get(f"/api/projects/{project['id']}/sessions").json()[0]["id"]
    questions = client.get(f"/api/sessions/{sid}/questions").json()
    assert questions[0]["kind"] == "approval"
    assert questions[0]["meta"] == {"action": "gh_open_pr"}


def test_chat_rejects_foreign_session(client):
    from sqlmodel import Session as SqlSession
    from sqlmodel import select as sqlselect

    from hestia.registry.db import engine
    from hestia.registry.models import Message
    from hestia.registry.models import Session as ChatSession

    alpha = _mk_project(client, name="aa")
    beta = _mk_project(client, name="bb")
    provider = _mk_provider(client)
    with SqlSession(engine()) as db:
        chat = ChatSession(project_id=alpha["id"], title="a session")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        session_id = chat.id

    resp = client.post(
        f"/api/projects/{beta['id']}/chat",
        json={"message": "hi", "session_id": session_id, "provider_id": provider["id"]},
    )
    assert resp.status_code == 404
    with SqlSession(engine()) as db:
        assert db.exec(sqlselect(Message).where(Message.session_id == session_id)).all() == []


def test_goal_action_persists_on_session(client, monkeypatch):
    from sqlmodel import Session as SqlSession

    from hestia.registry.db import engine
    from hestia.registry.models import Session as ChatSession
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    goal = client.post(
        f"/api/projects/{project['id']}/goals", json={"title": "Ship it"}
    ).json()
    discussed = client.post(f"/api/goals/{goal['id']}/discuss").json()
    session_id = discussed["session_id"]

    with SqlSession(engine()) as db:
        assert db.get(ChatSession, session_id).action == "goal"

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
        json={"message": "continue", "session_id": session_id, "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert "Goal mode" in seen["system"]


def test_chat_persists_tool_history(client, monkeypatch):
    import json as jsonlib

    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    captured = {}
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            yield {"type": "token", "text": "checking "}
            yield {
                "type": "message",
                "content": "checking",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_agents_md", "arguments": "{}"},
                    }
                ],
            }
            yield {"type": "tool_call", "id": "call_1", "name": "read_agents_md", "arguments": {}}
            yield {
                "type": "tool_result",
                "id": "call_1",
                "name": "read_agents_md",
                "ok": True,
                "preview": '"# demo"',
            }
            yield {"type": "message", "content": "Done.", "tool_calls": []}
        else:
            captured["messages"] = messages
            yield {"type": "message", "content": "Again.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "read it", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    session_id = client.get(f"/api/projects/{project['id']}/sessions").json()[0]["id"]
    rows = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [r["role"] for r in rows] == ["user", "assistant", "tool", "assistant"]
    assert jsonlib.loads(rows[1]["tool_calls"])[0]["id"] == "call_1"
    assert rows[2]["tool_call_id"] == "call_1"
    assert rows[2]["name"] == "read_agents_md"
    assert rows[2]["ok"] is True
    assert rows[3]["content"] == "Done."

    # the next turn replays valid assistant/tool pairs to the provider
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "again", "session_id": session_id, "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    sent = captured["messages"]
    assert any(m.get("tool_calls") for m in sent if m["role"] == "assistant")
    tool_rows = [m for m in sent if m["role"] == "tool"]
    assert tool_rows and tool_rows[0]["tool_call_id"] == "call_1"


def test_chat_heartbeat(client, monkeypatch):
    import asyncio

    from hestia.agent import loop as agent_loop
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)

    async def slow_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        await asyncio.sleep(0.5)
        yield {"type": "message", "content": "late", "tool_calls": []}

    from hestia import runs as runs_mod

    monkeypatch.setattr(agent_loop, "run_turn", slow_run_turn)
    monkeypatch.setattr(runs_mod, "HEARTBEAT_SECONDS", 0.1)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "slow", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert ": ping" in resp.text
    assert "late" in resp.text


def test_chat_usage_tracking(client, monkeypatch):
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def stream_chat(self, messages, tools=None):
            yield {"choices": [{"delta": {"content": "hello "}}]}
            yield {"choices": [{"delta": {"content": "world"}}]}
            yield {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 5}}

    monkeypatch.setattr(chat_router, "provider_client", FakeClient)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hi", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert "hello" in resp.text

    data = client.get(f"/api/projects/{project['id']}/usage").json()
    assert data["total"] == {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "tokens": 16,
        "runs": 1,
    }
    assert data["by_action"][0]["action"] == "chat"
    assert data["by_session"][0]["tokens"] == 16
    assert data["by_session"][0]["title"] == "hi"

    assert client.get("/api/projects/999/usage").status_code == 404


def test_user_note_in_chat_prompt(client, monkeypatch):
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def stream_chat(self, messages, tools=None):
            seen["system"] = messages[0]["content"]
            yield {"choices": [{"delta": {"content": "ok"}}]}

    monkeypatch.setattr(chat_router, "provider_client", FakeClient)
    client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "call me Sam", "provider_id": provider["id"]},
    )
    assert "About the owner" in seen["system"]
    assert "set_owner_name" in seen["system"]
    assert "remember_preference" in seen["system"]


def test_btw_streams_answer_with_compacted_context(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = client.post(
        "/api/providers",
        json={"name": "fake-btw", "base_url": "http://x", "api_key_env": "NOPE", "model": "m"},
    ).json()

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        assert messages[0]["content"].startswith("You are the project agent for 'demo'")
        assert "user: what changed?" in messages[0]["content"]
        assert messages[-1] == {"role": "user", "content": "why blue?"}
        # read-only: no writes, no delegation, no image generation
        assert "workspace_write" not in registry._tools
        assert "run_subagent" not in registry._tools
        assert "generate_image" not in registry._tools
        yield {"type": "token", "text": "Rayleigh "}
        yield {"type": "token", "text": "scattering."}
        yield {"type": "message", "content": "Rayleigh scattering.", "tool_calls": []}
        yield {"type": "usage", "usage": {"prompt_tokens": 5, "completion_tokens": 3}}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/btw",
        json={
            "question": "why blue?",
            "provider_id": provider["id"],
            "context": [
                {"role": "user", "content": "what changed?"},
                {"role": "assistant", "content": "a lot"},
            ],
        },
    )
    assert resp.status_code == 200
    assert '"event": "token"' in resp.text
    assert "Rayleigh " in resp.text
    assert '"event": "done"' in resp.text


def test_chat_always_streams_thinking(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        yield {"type": "thinking", "text": "pondering the question"}
        yield {"type": "message", "content": "answer", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hi", "provider_id": provider["id"]},
    )
    assert '"event": "thinking"' in resp.text
    assert "pondering the question" in resp.text

    # The setting now only controls the UI default-open state, not the stream.
    client.put("/api/settings", json={"show_thinking": "0"})
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hi again", "provider_id": provider["id"]},
    )
    assert '"event": "thinking"' in resp.text
    assert "pondering the question" in resp.text
    assert '"event": "message"' in resp.text

    # Thinking is persisted with the assistant reply (survives reload), and is
    # not replayed to the provider.
    sid = client.get(f"/api/projects/{project['id']}/sessions").json()[0]["id"]
    rows = client.get(f"/api/sessions/{sid}/messages").json()
    assistant = [m for m in rows if m["role"] == "assistant" and m["content"] == "answer"]
    assert assistant and assistant[-1]["thinking"] == "pondering the question"


def test_memory_checkpoint_creates_candidate(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        yield {"type": "message", "content": "Just chatting.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hello", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert calls["n"] >= 2  # main turn + blocking checkpoint

    candidates = client.get(f"/api/projects/{project['id']}/memory/candidates").json()
    assert len(candidates) == 1
    assert candidates[0]["source"] == "checkpoint"
    assert candidates[0]["status"] == "pending"


def test_memory_checkpoint_accepts_written_memory(client, monkeypatch):
    import json

    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            yield {"type": "message", "content": "answer", "tool_calls": []}
            return
        args = {
            "type": "gotcha",
            "title": "Checkpoint gotcha",
            "statement": "The checkpoint wrote this.",
            "tags": ["test"],
        }
        result = registry.get("memory_create").handler(ctx, args)
        yield {"type": "tool_call", "id": "c1", "name": "memory_create", "arguments": args}
        yield {
            "type": "tool_result",
            "id": "c1",
            "name": "memory_create",
            "ok": True,
            "preview": json.dumps(result)[:2000],
        }
        yield {"type": "message", "content": "", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "hello", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert calls["n"] >= 2
    assert client.get(f"/api/projects/{project['id']}/memory/candidates").json() == []
    from hestia import totem_store

    titles = [m["title"] for m in totem_store.list_all(project["local_path"])]
    assert "Checkpoint gotcha" in titles


def test_user_required_tool(client, monkeypatch):
    from sqlmodel import Session as SqlSession

    from hestia import notify
    from hestia import questions as questions_mod
    from hestia.agent.loop import AgentPause
    from hestia.registry.db import engine
    from hestia.registry.models import Session as ChatSession
    from hestia.tools import questions as question_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    monkeypatch.setenv("NTFY_TOPIC", "home")

    class FakeResp:
        status_code = 200
        text = "ok"

    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append(url) or FakeResp())

    with SqlSession(engine()) as db:
        chat = ChatSession(project_id=project["id"], title="u")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        ctx = ProjectContext(
            project_id=project["id"],
            name=project["name"],
            repo_url=project["repo_url"],
            local_path=Path(project["local_path"]),
            session_id=chat.id,
        )
        tools = {t.name: t for t in question_tools.make_tools(db)}
        with pytest.raises(AgentPause) as exc:
            tools["user_required"].handler(ctx, {
                "action": "Sign the release commit with GPG",
                "command": "git commit -S -m 'release'",
                "details": "The release tag needs a signed commit.",
            })
        payload = exc.value.payload
        assert payload["kind"] == "user_required"
        assert payload["question"] == "Sign the release commit with GPG"
        assert payload["meta"]["command"] == "git commit -S -m 'release'"
        assert payload["options"] == ["Done", "Skip"]
        rows = questions_mod.list_for_session(db, chat.id)
        assert len(rows) == 1
        assert rows[0].kind == "user_required" and rows[0].status == "open"
        assert questions_mod.as_dict(rows[0])["meta"]["command"] == "git commit -S -m 'release'"

        bare = ProjectContext(project_id=1, name="x", repo_url="", local_path=Path("."))
        with pytest.raises(ValueError):
            tools["user_required"].handler(bare, {"action": "x"})

    assert calls == ["https://ntfy.sh/home"]


def test_chat_user_required_event(client, monkeypatch):
    from hestia.agent import loop as agent_loop
    from hestia.agent.loop import AgentPause

    project = _mk_project(client)
    provider = _mk_provider(client)
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            try:
                registry.get("user_required").handler(
                    ctx, {"action": "Run the migration", "command": "sudo migrate"}
                )
            except AgentPause as pause:
                yield {"type": "question", **pause.payload}
                return
        yield {"type": "message", "content": "ok", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "go", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert '"event": "question"' in resp.text
    assert '"kind": "user_required"' in resp.text
    assert "sudo migrate" in resp.text


def test_chat_decision_feedback_retry(client, monkeypatch):
    from hestia.agent import loop as agent_loop
    from hestia.decision.config import Settings
    from hestia.decision.scoring import Failure
    from hestia.decision.service import Evaluation
    from hestia.routers import chat as chat_router

    project = _mk_project(client)
    provider = _mk_provider(client)
    calls = {"n": 0}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        calls["n"] += 1
        yield {"type": "message", "content": f"attempt {calls['n']}", "tool_calls": []}

    class FakeDecision:
        def __init__(self):
            self.evaluated = 0

        def settings(self):
            return Settings(enabled=True, base_url="http://laya", max_feedback_retries=1)

        async def evaluate(self, turn):
            self.evaluated += 1
            if self.evaluated == 1:
                return Evaluation("answer", "fail", 0.3, [], [Failure("requirements_met", "do the thing", 0.2, 0.9)], [], {}, None, None)
            return Evaluation("answer", "pass", 0.9, [], [], [], {}, None, None)

    fake = FakeDecision()
    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    monkeypatch.setattr(chat_router, "DecisionService", lambda: fake)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "do the thing", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert '"event": "decision"' in resp.text
    assert fake.evaluated == 2 and calls["n"] >= 2

    sid = client.get(f"/api/projects/{project['id']}/sessions").json()[0]["id"]
    messages = client.get(f"/api/sessions/{sid}/messages").json()
    assert any(msg["role"] == "user" and "Decision engine evaluation" in (msg["content"] or "") for msg in messages)


def test_chat_yolo_runs_in_sandbox(client, monkeypatch):
    from pathlib import Path

    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.put(f"/api/projects/{project['id']}", json={"write_mode": "yolo"})
    real_root = Path(project["local_path"])

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        (ctx.repo_path() / "agent.txt").write_text("hi\n")
        yield {"type": "message", "content": "done", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/projects/{project['id']}/chat",
        json={"message": "add a file", "provider_id": provider["id"]},
    )
    assert resp.status_code == 200
    assert '"event": "sandbox"' in resp.text
    assert not (real_root / "agent.txt").exists()  # real clone untouched

    info = client.get(f"/api/projects/{project['id']}/sandbox").json()
    assert any("agent.txt" in text for text in info["patches"].values())
