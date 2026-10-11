"""Schedules, event triggers, background jobs, and one-shot runs."""

from tests.api.conftest import _mk_project, _mk_provider


def test_schedules_crud_and_run(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from sqlmodel import Session as SqlSession

    from hestia import scheduler
    from hestia.registry.db import engine
    from hestia.registry.models import Schedule

    project = _mk_project(client)
    pid = project["id"]
    provider = _mk_provider(client)
    client.post("/api/agents", json={"name": "github-scan", "provider_id": provider["id"]})

    assert client.get(f"/api/projects/{pid}/schedules").json() == []
    assert client.post(
        f"/api/projects/{pid}/schedules", json={"action": "nope"}
    ).status_code == 400

    sched = client.post(
        f"/api/projects/{pid}/schedules",
        json={"action": "github-scan", "instruction": "Summarize today ({date})", "interval_minutes": 5},
    ).json()
    assert sched["enabled"] is True and sched["last_run_at"] is None

    updated = client.put(
        f"/api/schedules/{sched['id']}", json={"enabled": False, "interval_minutes": 0}
    ).json()
    assert updated["enabled"] is False and updated["interval_minutes"] == 1

    with SqlSession(engine()) as db:
        # not due right after creation; due once the interval has passed
        assert scheduler.due_schedules(db) == []
        row = db.get(Schedule, sched["id"])
        row.enabled = True
        row.last_run_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.add(row)
        db.commit()
        assert [s.id for s in scheduler.due_schedules(db)] == [sched["id"]]

    from hestia.agent import loop as agent_loop

    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["instruction"] = messages[-1]["content"]
        yield {"type": "message", "content": "Digest written.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    result = client.post(f"/api/schedules/{sched['id']}/run").json()
    assert result["last_status"] == "ok"
    assert result["last_report"] == "Digest written."
    assert result["last_run_at"]
    assert "{" not in seen["instruction"] and "(" in seen["instruction"]

    assert client.delete(f"/api/schedules/{sched['id']}").status_code == 204
    assert client.post(f"/api/schedules/{sched['id']}/run").status_code == 404


def test_event_trigger_matching_and_run(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession, select

    from hestia import events, scheduler
    from hestia.registry.db import engine
    from hestia.registry.models import Event, Project, Schedule

    project = _mk_project(client)
    pid = project["id"]
    provider = _mk_provider(client)

    with SqlSession(engine()) as db:
        row = db.get(Project, pid)
        row.default_provider_id = provider["id"]
        db.add(row)
        db.commit()
        db.add(
            Schedule(
                project_id=pid,
                action="chat",
                instruction="Handle {event}: {event_title}",
                trigger="event",
                event="ci_failure",
            )
        )
        db.add(
            Schedule(
                project_id=pid,
                action="chat",
                instruction="never",
                trigger="event",
                event="pr_opened",
            )
        )
        db.commit()
        events.emit(db, pid, "ci_failure", {"title": "CI broken", "url": "http://x"}, key="run:1")
        events.emit(db, pid, "ci_failure", {"title": "CI broken", "url": "http://x"}, key="run:1")
        db.commit()
        assert len(db.exec(select(Event).where(Event.project_id == pid)).all()) == 1
        plan, handle_ids = scheduler._event_plan(db)
        assert len(plan) == 1
        assert plan[0][1]["payload"]["title"] == "CI broken"
        assert handle_ids

    from hestia.agent import loop as agent_loop

    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["instruction"] = messages[-1]["content"]
        yield {"type": "message", "content": "handled", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)

    result = asyncio.run(scheduler.run_schedule(plan[0][0], event=plan[0][1]))
    assert result["last_status"] == "ok", result.get("last_report")
    assert "CI broken" in seen["instruction"]


def test_schedule_agent_tools(client):
    from sqlmodel import Session as SqlSession, select

    from hestia.registry.db import engine
    from hestia.registry.models import Project, Schedule
    from hestia.tools import schedules as schedule_tools
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    with SqlSession(engine()) as db:
        project_obj = db.get(Project, project["id"])
        ctx = ProjectContext.from_project(project_obj)
        tools = {t.name: t for t in schedule_tools.make_tools(db)}
        created = tools["schedule_create"].handler(
            ctx,
            {"instruction": "Check the feed every Friday", "interval_minutes": 10080},
        )
        assert created["interval_minutes"] == 10080
        listed = tools["schedule_list"].handler(ctx, {})
        assert any(s["id"] == created["id"] for s in listed)
        tools["schedule_cancel"].handler(ctx, {"id": created["id"]})
        assert db.exec(
            select(Schedule).where(Schedule.project_id == project["id"])
        ).all() == []


def test_background_task_lifecycle(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession, select

    from hestia import jobs
    from hestia.registry.db import engine
    from hestia.registry.models import BackgroundTask, Message
    from hestia.registry.models import Session as ChatSession

    project = _mk_project(client)
    with SqlSession(engine()) as db:
        cs = ChatSession(project_id=project["id"], title="bg")
        db.add(cs)
        db.commit()
        db.refresh(cs)
        sid = cs.id

    monkeypatch.setattr(jobs.manager, "enqueue", lambda job_id: None)

    async def fake_exec(db, job, project_obj):
        return "did the thing", None, {}

    monkeypatch.setattr(jobs, "_execute_job", fake_exec)

    job_id = jobs.submit(
        project_id=project["id"],
        session_id=sid,
        kind="agent",
        instruction="do it",
        description="test job",
        action="chat",
    )
    asyncio.run(jobs.manager._run(job_id))

    with SqlSession(engine()) as db:
        job = db.get(BackgroundTask, job_id)
        assert job.status == "completed"
        assert job.result == "did the thing"
        assert job.notified is True
        notes = db.exec(
            select(Message).where(
                Message.session_id == sid, Message.role == "notification"
            )
        ).all()
        assert notes and "task.completed" in notes[0].content


def test_background_stop_and_reconcile(client, monkeypatch):
    from sqlmodel import Session as SqlSession, select

    from hestia import jobs
    from hestia.registry.db import engine
    from hestia.registry.models import BackgroundTask

    project = _mk_project(client)
    monkeypatch.setattr(jobs.manager, "enqueue", lambda job_id: None)

    job_id = jobs.submit(
        project_id=project["id"],
        session_id=None,
        kind="agent",
        instruction="x",
        description="y",
    )
    stopped = jobs.stop(job_id)
    assert stopped["status"] == "stopped"

    with SqlSession(engine()) as db:
        db.add(
            BackgroundTask(
                project_id=project["id"],
                kind="agent",
                status="running",
                instruction="x",
                description="y",
            )
        )
        db.commit()

    jobs._reconcile()
    with SqlSession(engine()) as db:
        lost = db.exec(
            select(BackgroundTask).where(BackgroundTask.status == "lost")
        ).all()
        assert any(j.project_id == project["id"] for j in lost)


def test_run_subagent_background_returns_job(client, monkeypatch):
    from sqlmodel import Session as SqlSession, select

    from hestia import jobs
    from hestia.registry.db import engine
    from hestia.registry.models import BackgroundTask, Project
    from hestia.tools import subagents
    from hestia.tools.registry import ProjectContext

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.post(
        "/api/agents",
        json={"name": "explore", "provider_id": provider["id"], "tools": ["repo"], "max_turns": 2},
    )
    monkeypatch.setattr(jobs.manager, "enqueue", lambda job_id: None)

    with SqlSession(engine()) as db:
        project_obj = db.get(Project, project["id"])
        ctx = ProjectContext.from_project(project_obj)
        registry_tools = {t.name: t for t in subagents.make_tools(db)}
        result = registry_tools["run_subagent"].handler(
            ctx,
            {"action": "explore", "task": "look around", "run_in_background": True, "description": "bg look"},
        )
        assert result["status"] == "queued"
        job = db.get(BackgroundTask, result["job_id"])
        assert job.kind == "subagent" and job.action == "explore"


def test_run_once_registers_db_tools(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia.agent import run as run_mod
    from hestia.registry.db import engine
    from hestia.registry.models import Project, Provider

    project = _mk_project(client)
    provider = _mk_provider(client)
    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["tools"] = [t.name for t in registry.all()]
        yield {"type": "message", "content": "ok", "tool_calls": []}

    monkeypatch.setattr(run_mod.agent_loop, "run_turn", fake_run_turn)
    with SqlSession(engine()) as db:
        report, error, tokens = asyncio.run(
            run_mod.run_once(
                db.get(Project, project["id"]),
                db.get(Provider, provider["id"]),
                "sys",
                "user",
                groups="tasks,reminders,watches,automations",
                tasks_db=db,
            )
        )
    assert error is None
    for name in ("task_create", "remind_me", "watch_add", "schedule_create"):
        assert name in seen["tools"]


def test_daily_plan_and_weekly_review_gates(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import notify, scheduler, settings
    from hestia.registry.db import engine

    _mk_project(client)
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: calls.append(a))

    client.put(
        "/api/settings",
        json={
            "daily_plan_enabled": "1",
            "daily_plan_time": "00:00",
            "weekly_review_enabled": "1",
            "weekly_review_time": "00:00",
        },
    )
    with SqlSession(engine()) as db:
        day = settings.local_now(db).weekday()
    client.put("/api/settings", json={"weekly_review_day": str(day)})

    with SqlSession(engine()) as db:
        asyncio.run(scheduler._maybe_send_daily_plan(db))
        asyncio.run(scheduler._maybe_send_daily_plan(db))
    assert len([c for c in calls if c[0] == "Daily plan"]) == 1

    with SqlSession(engine()) as db:
        asyncio.run(scheduler._maybe_send_weekly_review(db))
        asyncio.run(scheduler._maybe_send_weekly_review(db))
    assert len([c for c in calls if c[0] == "Weekly review"]) == 1

    assert client.put("/api/settings", json={"weekly_review_time": "25:00"}).status_code == 400
    assert client.put("/api/settings", json={"weekly_review_day": "9"}).status_code == 400


def test_background_subagent_uses_delegation_mode(client, monkeypatch):
    import asyncio

    from sqlmodel import Session as SqlSession

    from hestia import jobs
    from hestia.agent import run as run_mod
    from hestia.registry.db import engine
    from hestia.registry.models import BackgroundTask

    project = _mk_project(client)
    provider = _mk_provider(client)
    client.put(f"/api/projects/{project['id']}/git-writes", json={"enabled": True})
    client.post(
        "/api/agents",
        json={
            "name": "bulk-editor",
            "provider_id": provider["id"],
            "tools": ["repo", "workspace", "memory", "writes", "tasks", "images"],
            "mode": "write",
            "max_turns": 2,
        },
    )
    seen = {}

    async def fake_run_turn(ctx, client_, registry, messages, max_turns=None, run=None, timeout=None):
        seen["tools"] = {t.name for t in registry.all()}
        seen["system"] = messages[0]["content"]
        yield {"type": "message", "content": "ok", "tool_calls": []}

    monkeypatch.setattr(run_mod.agent_loop, "run_turn", fake_run_turn)
    monkeypatch.setattr(jobs.manager, "enqueue", lambda job_id: None)

    job_id = jobs.submit(
        project_id=project["id"],
        session_id=None,
        kind="subagent",
        instruction="write the docs",
        description="docs overhaul",
        action="bulk-editor",
    )
    asyncio.run(jobs.manager._run(job_id))

    assert {"write_file", "workspace_write", "memory_create"} <= seen["tools"]
    assert not seen["tools"] & {
        "git_create_branch",
        "git_commit",
        "git_push",
        "gh_open_pr",
        "task_create",
        "generate_image",
        "notify",
    }
    assert "Write mode" in seen["system"]
    with SqlSession(engine()) as db:
        assert db.get(BackgroundTask, job_id).status == "completed"
