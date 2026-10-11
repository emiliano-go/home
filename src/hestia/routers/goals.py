"""Goals: discuss an outcome, keep a spec, plan it into a milestone + tasks."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from hestia import settings, actions, goals, milestones as milestones_mod, repos, totem_store, usage
from hestia.agent import loop as agent_loop
from hestia.agent.prompt import build_system_prompt
from hestia.providers.base import OpenAIClient, resolve_api_key
from hestia.registry.db import session
from hestia.registry.models import Goal, Message, Milestone, Project, Provider, Task
from hestia.registry.models import Session as ChatSession
from hestia.tools import build_registry
from hestia.tools import tasks as task_tools
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["goals"])

DISCUSS_SEED = """\
I want to work on this goal:

**{title}**

{description}

Success criteria: {criteria}

Let's refine it. Ask me focused questions (one or two at a time), and keep a draft \
spec updated in the workspace at {spec_path} with workspace_write as we go. When \
the goal is clear, tell me to press "Generate board" on the Goals tab.
"""

PLAN_PROMPT = """\
Plan this goal into an executable board.

## Goal
Title: {title}
Success criteria: {criteria}
Description: {description}

## Discussion so far
{transcript}

Do this, then stop:
1. Read the repository, docs, and Totem memory as needed.
2. Write a concise spec to the workspace at exactly {spec_path}, and a plan at {plan_path}.
3. Create between 3 and 8 concrete tasks with task_create. Every task must pass
   milestone_id={milestone_id} and a short title, one-line description, priority,
   and acceptance (how to verify it is done). Use depends_on with the ids of
   tasks that must finish first; create tasks in order so you can reference the
   ids returned by earlier task_create calls.
4. End with a short plain-text report: the spec path, plan path, and the tasks created.
"""

CONVERGE_PROMPT = """\
Assess the board against this goal and its spec, and append missing work.

## Goal
Title: {title}
Success criteria: {criteria}
Spec: {spec_path}

Read the spec, the repository, and the current board (task_list). If required work
is missing, append concrete tasks with task_create (milestone_id={milestone_id},
acceptance criteria, depends_on where useful, no duplicates of existing tasks).
Do not modify the spec. End with a short report: gaps found and tasks added.
"""


def _goal_or_404(goal_id: int, s: Session) -> Goal:
    goal = s.get(Goal, goal_id)
    if not goal:
        raise HTTPException(404, "goal not found")
    return goal


def _spec_path(goal: Goal) -> str:
    return goal.spec_path or f"goals/{goals.slugify(goal.title)}/spec.md"


def _transcript(s: Session, session_id: str | None, limit: int = 20) -> str:
    if not session_id:
        return "(no discussion yet)"
    rows = s.exec(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    if not rows:
        return "(no discussion yet)"
    return "\n".join(
        f"{m.role}: {(m.content or '')[:500]}" for m in reversed(rows)
    )


def _provider_for(s: Session, project: Project, body: dict) -> Provider:
    agent = actions.resolve_action(s, "goal")
    provider_id = (
        body.get("provider_id")
        or (agent.provider_id if agent else None)
        or project.default_provider_id
    )
    provider = s.get(Provider, provider_id) if provider_id else None
    if not provider:
        raise HTTPException(400, "no provider configured for this project")
    return actions.effective_provider(agent, provider)


@router.get("/projects/{project_id}/goals")
def list_goals(project_id: int, s: Session = Depends(session)):
    if not s.get(Project, project_id):
        raise HTTPException(404, "project not found")
    rows = s.exec(select(Goal).where(Goal.project_id == project_id).order_by(Goal.id)).all()
    return [goals.as_dict(g, goals.progress(s, g)) for g in rows]


@router.post("/projects/{project_id}/goals", status_code=201)
def create_goal(project_id: int, body: dict, s: Session = Depends(session)):
    if not s.get(Project, project_id):
        raise HTTPException(404, "project not found")
    try:
        goal = goals.create(
            s,
            project_id,
            title=body.get("title", ""),
            description=body.get("description", ""),
            success_criteria=body.get("success_criteria", ""),
        )
    except goals.InvalidGoal as e:
        raise HTTPException(400, str(e))
    return goals.as_dict(goal)


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int, s: Session = Depends(session)):
    goal = _goal_or_404(goal_id, s)
    return goals.as_dict(goal, goals.progress(s, goal))


@router.put("/goals/{goal_id}")
def update_goal(goal_id: int, body: dict, s: Session = Depends(session)):
    goal = _goal_or_404(goal_id, s)
    try:
        goals.update(s, goal, body)
    except goals.InvalidGoal as e:
        raise HTTPException(400, str(e))
    return goals.as_dict(goal, goals.progress(s, goal))


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, s: Session = Depends(session)):
    goals.delete(s, _goal_or_404(goal_id, s))


@router.post("/goals/{goal_id}/discuss")
def discuss_goal(goal_id: int, s: Session = Depends(session)):
    """Open (or reuse) the goal's discussion session. Returns a seed first time."""
    goal = _goal_or_404(goal_id, s)
    spec_path = _spec_path(goal)
    if goal.session_id and s.get(ChatSession, goal.session_id):
        return {"session_id": goal.session_id, "seed": None, "spec_path": spec_path}
    chat = ChatSession(project_id=goal.project_id, title=f"Goal: {goal.title}", action="goal")
    s.add(chat)
    s.commit()
    s.refresh(chat)
    goal.session_id = chat.id
    goal.spec_path = spec_path
    s.add(goal)
    s.commit()
    return {
        "session_id": chat.id,
        "seed": DISCUSS_SEED.format(
            title=goal.title,
            description=goal.description or "(no description yet)",
            criteria=goal.success_criteria or "(not set)",
            spec_path=spec_path,
        ),
        "spec_path": spec_path,
    }


async def _run_goal_agent(s: Session, goal: Goal, provider: Provider, system: str, user: str):
    ctx = ProjectContext.from_project(s.get(Project, goal.project_id))
    registry = build_registry()
    for tool in task_tools.make_tools(s):
        registry.register(tool)
    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        provider.model,
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    final = ""
    tokens: dict = {}
    async for event in agent_loop.run_turn(ctx, client, registry, messages):
        if event["type"] == "usage":
            usage.merge(tokens, event.get("usage"))
            continue
        if event["type"] == "message":
            final = event.get("content", "")
        elif event["type"] == "error":
            return final, event["message"], tokens
    return final, None, tokens


def _goal_system(s: Session, goal: Goal, provider: Provider, task: str, extra: str) -> str:
    project = s.get(Project, goal.project_id)
    agent = actions.resolve_action(s, "goal")
    digest = totem_store.digest(repos.memory_root(project), task=task)
    system = build_system_prompt(
        ProjectContext.from_project(project),
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task=task,
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    return system + "\n\n" + extra


@router.post("/goals/{goal_id}/plan")
def plan_goal(goal_id: int, body: dict, s: Session = Depends(session)):
    """One-shot agent run: spec + plan + milestone + dependency-aware tasks."""
    goal = _goal_or_404(goal_id, s)
    project = s.get(Project, goal.project_id)
    provider = _provider_for(s, project, body)

    milestone = s.get(Milestone, goal.milestone_id) if goal.milestone_id else None
    if milestone is None:
        milestone = milestones_mod.create(
            s, project.id, title=goal.title, description=goal.description[:500]
        )
    spec_path = _spec_path(goal)
    plan_path = f"goals/{goals.slugify(goal.title)}/plan.md"
    transcript = _transcript(s, goal.session_id)
    prompt = PLAN_PROMPT.format(
        title=goal.title,
        criteria=goal.success_criteria or "(not set)",
        description=goal.description or "(no description)",
        transcript=transcript,
        spec_path=spec_path,
        plan_path=plan_path,
        milestone_id=milestone.id,
    )
    system = _goal_system(s, goal, provider, f"Plan goal: {goal.title}", prompt)
    report, error, tokens = asyncio.run(
        _run_goal_agent(s, goal, provider, system, f"Plan the goal: {goal.title}")
    )
    usage.record(s, project.id, action="goal-plan", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)

    goal.milestone_id = milestone.id
    goal.spec_path = spec_path
    if goal.status == "drafting":
        goal.status = "active"
    s.add(goal)
    s.commit()
    s.refresh(goal)
    task_rows = s.exec(select(Task).where(Task.milestone_id == milestone.id)).all()
    return {
        "report": report,
        "spec_path": spec_path,
        "plan_path": plan_path,
        "milestone_id": milestone.id,
        "task_ids": [t.id for t in task_rows],
        "goal": goals.as_dict(goal, goals.progress(s, goal)),
    }


@router.post("/goals/{goal_id}/converge")
def converge_goal(goal_id: int, body: dict, s: Session = Depends(session)):
    """Read-only gap check; the only write is appending tasks."""
    goal = _goal_or_404(goal_id, s)
    project = s.get(Project, goal.project_id)
    provider = _provider_for(s, project, body)
    prompt = CONVERGE_PROMPT.format(
        title=goal.title,
        criteria=goal.success_criteria or "(not set)",
        spec_path=_spec_path(goal),
        milestone_id=goal.milestone_id or 0,
    )
    system = _goal_system(s, goal, provider, f"Converge goal: {goal.title}", prompt)
    report, error, tokens = asyncio.run(
        _run_goal_agent(s, goal, provider, system, f"Converge the goal: {goal.title}")
    )
    usage.record(s, project.id, action="goal-converge", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)
    return {"report": report, "goal": goals.as_dict(goal, goals.progress(s, goal))}
