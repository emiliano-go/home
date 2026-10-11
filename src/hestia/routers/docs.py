"""Generate project documents (architecture, onboarding, ADRs) from Totem memory.

A one-shot server-side agent run, like triage: the agent reads memory and the
repository and writes the document into the project workspace.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hestia import settings, actions, repos, totem_store, usage
from hestia.agent.prompt import build_system_prompt
from hestia.agent.run import run_once
from hestia.registry.db import session
from hestia.registry.models import Project, Provider
from hestia.tools.registry import ProjectContext

router = APIRouter(prefix="/api", tags=["docs"])

DOC_KINDS = {
    "architecture": ("Architecture document", "ARCHITECTURE.md"),
    "onboarding": ("Onboarding guide", "ONBOARDING.md"),
    "adr": ("Architecture decision record", None),
}

DOC_PROMPT = """\
Write the project's {label} based on its Totem memory, repository, and docs.
Write it to the workspace with workspace_write at exactly this path: {path}
Then stop and return one short paragraph: the path written and what it covers.
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "decision"


@router.post("/projects/{project_id}/docs")
def generate_doc(project_id: int, body: dict, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    kind = str(body.get("kind", "architecture")).lower()
    if kind not in DOC_KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(DOC_KINDS)}")
    label, path = DOC_KINDS[kind]
    if kind == "adr":
        topic = (body.get("topic") or "").strip()
        if not topic:
            raise HTTPException(400, "topic is required for an ADR")
        label = f"ADR: {topic}"
        path = f"adr/{_slug(topic)}.md"

    agent = actions.resolve_action(s, "docs")
    provider_id = (
        body.get("provider_id")
        or (agent.provider_id if agent else None)
        or project.default_provider_id
    )
    provider = s.get(Provider, provider_id) if provider_id else None
    provider = actions.effective_provider(agent, provider)
    if not provider:
        raise HTTPException(400, "no provider configured for this project")

    digest = totem_store.digest(repos.memory_root(project), task=label)
    system = build_system_prompt(
        ProjectContext.from_project(project),
        agents_md=project.agents_md,
        memory_context=digest.get("context", ""),
        user_task=label,
        extra_context=settings.prompt_context(s),
    )
    if agent and agent.system_prompt:
        system += f"\n\n## Agent instructions\n{agent.system_prompt}"
    system += "\n\n" + DOC_PROMPT.format(label=label, path=path)

    report, error, tokens = asyncio.run(
        run_once(
            project,
            provider,
            system,
            f"Generate: {label}",
            groups=actions.ACTIONS_BY_KEY["docs"]["tools"],
            tasks_db=s,
        )
    )
    usage.record(s, project.id, action="docs", model=provider.model, usage=tokens)
    if error:
        raise HTTPException(502, error)
    return {"report": report, "path": path, "kind": kind}
