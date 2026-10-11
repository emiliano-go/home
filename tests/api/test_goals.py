"""Goal discussion, planning, and convergence."""

from tests.api.conftest import _mk_project, _mk_provider


def test_goal_crud_and_discuss(client):
    project = _mk_project(client)
    pid = project["id"]
    assert client.get(f"/api/projects/{pid}/goals").json() == []

    goal = client.post(
        f"/api/projects/{pid}/goals",
        json={"title": "Ship v1", "description": "first release", "success_criteria": "tests pass"},
    ).json()
    assert goal["status"] == "drafting"
    assert goal["progress"] is None

    first = client.post(f"/api/goals/{goal['id']}/discuss").json()
    assert first["session_id"] and first["seed"] and "Ship v1" in first["seed"]
    assert first["spec_path"] == "goals/ship-v1/spec.md"
    again = client.post(f"/api/goals/{goal['id']}/discuss").json()
    assert again["session_id"] == first["session_id"] and again["seed"] is None

    updated = client.put(f"/api/goals/{goal['id']}", json={"status": "active"}).json()
    assert updated["status"] == "active"
    assert client.post(f"/api/projects/{pid}/goals", json={"title": " "}).status_code == 400
    assert client.put(f"/api/goals/{goal['id']}", json={"status": "nope"}).status_code == 400
    assert client.get(f"/api/goals/999").status_code == 404

    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204
    assert client.get(f"/api/projects/{pid}/goals").json() == []


def test_goal_plan_and_converge(client, monkeypatch):
    from hestia.agent import loop as agent_loop

    project = _mk_project(client)
    provider = _mk_provider(client)
    goal = client.post(
        f"/api/projects/{project['id']}/goals",
        json={"title": "Add search", "success_criteria": "users can search"},
    ).json()

    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["system"] = messages[0]["content"]
        seen["tools"] = {t.name for t in registry.all()}
        yield {"type": "message", "content": "Planned: 3 tasks.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    resp = client.post(
        f"/api/goals/{goal['id']}/plan", json={"provider_id": provider["id"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["spec_path"] == "goals/add-search/spec.md"
    assert body["plan_path"] == "goals/add-search/plan.md"
    assert body["milestone_id"]
    assert "Add search" in seen["system"]
    assert "add-search/spec.md" in seen["system"]
    assert "acceptance" in seen["system"]
    assert {"task_create", "milestone_create"} <= seen["tools"]

    refreshed = client.get(f"/api/goals/{goal['id']}").json()
    assert refreshed["status"] == "active"
    assert refreshed["milestone_id"] == body["milestone_id"]

    resp = client.post(
        f"/api/goals/{goal['id']}/converge", json={"provider_id": provider["id"]}
    )
    assert resp.status_code == 200
    assert resp.json()["report"] == "Planned: 3 tasks."

    assert client.post("/api/goals/999/plan", json={}).status_code == 404
