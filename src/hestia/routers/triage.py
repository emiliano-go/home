"""Triage: turn a GitHub issue or PR into a plan file and board tasks.

One-shot server-side agent run (like the memory fixer), not a chat session.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hestia import settings, actions, overview, repos, taskboard, totem_store, usage
from hestia.agent import loop as agent_loop
from hestia.agent.prompt import build_system_prompt
from hestia.providers.base import OpenAIClient, resolve_api_key
from hestia.registry.db import session
from hestia.registry.models import Project, Provider
from hestia.tools import build_registry
from hestia.tools import tasks as task_tools
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["triage"])


def _repo_row(s: Session, project: Project, body: dict):
    """The repo selected by body['repo'], else the primary."""
    rows = repos.repos_for(s, project.id)
    if not rows:
        raise HTTPException(400, "project has no repositories")
    alias = (body.get("repo") or "").strip() or None
    if alias:
        row = next((r for r in rows if r.alias == alias), None)
        if row is None:
            raise HTTPException(404, f"unknown repo alias: {alias}")
        return row, rows
    return next((r for r in rows if r.is_primary), rows[0]), rows

TRIAGE_PROMPT = """\
You are triaging a {kind} from the project's GitHub repository into actionable work.

## {kind} #{number}
Title: {title}
URL: {url}

Body:
{body}

Do this, then stop:
1. Read the repository code, history, or memory you need to understand the work.
2. Write a concise implementation plan to the project workspace with workspace_write,
   at exactly this path: {plan_path}
3. Create between 2 and 6 concrete sub-tasks on the board with task_create. Give each a
   short title and a one-line description. Group them under a milestone only if one fits.
4. End with a short plain-text report: what the item asks for, the plan path, and the
   tasks you created.
"""


REVIEW_PROMPT = """\
Review this {kind} and report findings ordered by severity.

## {kind} #{number}
Title: {title}
URL: {url}

Body:
{body}

Do this, then stop:
1. Read the relevant code, diff, and tests as needed.
2. Write the review to the workspace with workspace_write at exactly {path}.
3. If there is concrete follow-up work, create at most 2 tasks with task_create
   (each with acceptance criteria).
4. End with a short plain-text report: verdict, top findings, and the path written.
"""


@router.post("/projects/{project_id}/github/review")
def review_item(project_id: int, body: dict, s: Session = Depends(session)):
    """One-shot code review of a PR or issue, written to the workspace."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    kind = str(body.get("kind", "pr")).lower()
    if kind not in ("issue", "issues", "pr", "prs"):
        raise HTTPException(400, "kind must be issue or pr")
    kind = "pr" if kind.startswith("pr") else "issue"
    number = body.get("number")
    if not number:
        raise HTTPException(400, "number is required")

    row, _rows = _repo_row(s, project, body)
    try:
        item = overview.github_item_for_url(
            row.repo_url, "prs" if kind == "pr" else "issues", int(number)
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"could not fetch GitHub item: {str(e)[:200]}")

    path = f"reviews/{kind}-{number}.md"
    agent = actions.resolve_action(s, "code-reviewer")
    provider_id = (
        body.get("provider_id")
        or (agent.provider_id if agent else None)
        or project.default_provider_id
    )
    provider = s.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent, provider)
    if provider is None:
        raise HTTPException(400, "no provider configured for this project")

    ctx = ProjectContext.from_project(project)
    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        provider.model,
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    registry = build_registry()
    for tool in task_tools.make_tools(s):
        registry.register(tool)

    digest = totem_store.digest(ctx.memory_path, task=item["title"])
    system = build_system_prompt(
        ctx,
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task=item["title"],
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + REVIEW_PROMPT.format(
        kind=item["kind"],
        number=number,
        title=item["title"],
        url=item.get("url") or "",
        body=(item.get("body") or "(no description)")[:6000],
        path=path,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Review {item['kind']} #{number}: {item['title']}"},
    ]
    async def run():
        final = ""
        tokens: dict = {}
        async for event in agent_loop.run_turn(
            ctx, client, registry, messages
        ):
            if event["type"] == "usage":
                usage.merge(tokens, event.get("usage"))
                continue
            if event["type"] == "message":
                final = event.get("content", "")
            if event["type"] == "error":
                return "", event["message"], tokens
        return final, None, tokens

    report, error, tokens = asyncio.run(run())
    usage.record(s, project.id, action="pr-review", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)
    return {"report": report, "path": path}


@router.post("/projects/{project_id}/triage")
def triage(project_id: int, body: dict, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    kind = str(body.get("kind", "issue")).lower()
    if kind not in ("issue", "issues", "pr", "prs"):
        raise HTTPException(400, "kind must be issue or pr")
    kind = "pr" if kind.startswith("pr") else "issue"
    number = body.get("number")
    if not number:
        raise HTTPException(400, "number is required")

    row, rows = _repo_row(s, project, body)
    try:
        item = overview.github_item_for_url(
            row.repo_url, "prs" if kind == "pr" else "issues", int(number)
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network / auth / rate limit
        raise HTTPException(502, f"could not fetch GitHub item: {str(e)[:200]}")

    plan_path = f"plans/{kind}-{number}.md"

    # Track the item immediately, even if the agent run later fails.
    parent = taskboard.create(
        s,
        project_id,
        title=f"#{number} {item['title']}",
        description=((item.get("body") or "")[:4000] + f"\n\n{item['url']}").strip(),
        status="backlog",
        priority="medium",
        repo=row.alias if len(rows) > 1 else None,
    )

    agent = actions.resolve_action(s, "triage")
    provider = s.get(Provider, agent.provider_id) if agent else None
    if provider is None and project.default_provider_id:
        provider = s.get(Provider, project.default_provider_id)
    provider = actions.effective_provider(agent, provider)
    if provider is None:
        raise HTTPException(400, "no provider configured for this project")

    ctx = ProjectContext.from_project(project)
    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        provider.model,
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    registry = build_registry()
    for tool in task_tools.make_tools(s):
        registry.register(tool)

    digest = totem_store.digest(ctx.memory_path, task=item["title"])
    system = build_system_prompt(
        ctx,
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task=item["title"],
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + TRIAGE_PROMPT.format(
        kind=item["kind"],
        number=number,
        title=item["title"],
        url=item.get("url") or "",
        body=(item.get("body") or "(no description)")[:6000],
        plan_path=plan_path,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Triage {item['kind']} #{number}: {item['title']}"},
    ]
    async def run():
        final = ""
        tokens: dict = {}
        async for event in agent_loop.run_turn(
            ctx, client, registry, messages
        ):
            if event["type"] == "usage":
                usage.merge(tokens, event.get("usage"))
                continue
            if event["type"] == "message":
                final = event.get("content", "")
            if event["type"] == "error":
                return "", event["message"], tokens
        return final, None, tokens

    report, error, tokens = asyncio.run(run())
    usage.record(s, project.id, action="triage", model=provider.model, usage=tokens)
    return {
        "report": report,
        "error": error,
        "task_id": parent.id,
        "path": plan_path,
    }
