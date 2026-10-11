"""Agent profiles: named main/sub agents with their own provider and tools."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from hestia.actions import ACTIONS, ACTIONS_BY_KEY, action_defaults
from hestia.providers.base import REASONING_EFFORTS
from hestia.registry.db import session
from hestia.registry.models import ActionDefault, AgentConfig, Provider

router = APIRouter(prefix="/api/agents", tags=["agents"])
actions_router = APIRouter(prefix="/api/actions", tags=["actions"])

PRESETS = {
    "explore": {
        "name": "explore",
        "system_prompt": (
            "You are an exploration subagent. Investigate the repository "
            "structure, files, and git history relevant to the task. Return "
            "file paths, symbols, and concise findings."
        ),
        "tools": "repo,files",
        "mode": "read",
        "max_turns": 6,
        "reasoning_effort": "low",
    },
    "github-scan": {
        "name": "github-scan",
        "system_prompt": (
            "You are a GitHub scanning subagent. Inspect commits, PRs, "
            "issues, and CI runs relevant to the task. Return titles, "
            "numbers, and statuses."
        ),
        "tools": "github,repo",
        "mode": "read",
        "max_turns": 6,
        "reasoning_effort": "low",
    },
    "memory-keeper": {
        "name": "memory-keeper",
        "system_prompt": (
            "You are a memory curation subagent. Search and review project "
            "memory: find gaps, stale entries, and missing decisions worth "
            "recording. Create or update memories where warranted."
        ),
        "tools": "memory",
        "mode": "write",
        "max_turns": 6,
        "reasoning_effort": "low",
    },
    "writer": {
        "name": "writer",
        "system_prompt": (
            "You are a writing subagent. Produce the deliverable in the "
            "project workspace with workspace_write (plans, specs, docs) and "
            "return a short summary with the file paths you wrote. When git "
            "writes are enabled you may also edit repo docs with write_file; "
            "the principal commits and opens the pull request."
        ),
        "tools": "workspace,repo,files,writes",
        "mode": "write",
        "max_turns": 8,
        "reasoning_effort": "high",
    },
    "bulk-editor": {
        "name": "bulk-editor",
        "system_prompt": (
            "You are a bulk editing subagent for large, simple, mechanical "
            "changes: doc sweeps, renames, typo fixes, repetitive edits. When "
            "git writes are enabled, edit files with write_file in small "
            "verifiable batches. Do not commit: the principal reviews the diff "
            "and commits. Report exactly what changed."
        ),
        "tools": "repo,files,writes,workspace",
        "mode": "write",
        "max_turns": 12,
        "reasoning_effort": "high",
    },
    "code-reviewer": {
        "name": "code-reviewer",
        "system_prompt": (
            "You are a read-only code review subagent. Read the relevant "
            "code and diffs, then return findings ordered by severity."
        ),
        "tools": "repo,files,github",
        "mode": "read",
        "max_turns": 8,
        "reasoning_effort": "high",
    },
    "image": {
        "name": "image",
        "system_prompt": (
            "You are an image generation agent. Turn the owner's request into "
            "vivid, detailed image prompts and call generate_image for each "
            "image. Keep the reply short and always include the returned "
            "markdown image links."
        ),
        "tools": "images,workspace",
        "mode": "write",
        "max_turns": 4,
        "reasoning_effort": "low",
    },
    "browser": {
        "name": "browser",
        "system_prompt": (
            "You drive a real browser. Use browser_task for multi-step web "
            "goals and the low-level browser tools for UI debugging; prefer "
            "web_fetch for reading a single static page."
        ),
        "tools": "browser",
        "mode": "write",
        "max_turns": 8,
        "reasoning_effort": "low",
    },
    "memory-writer": {
        "name": "memory-writer",
        "system_prompt": (
            "You are the memory writer. Read the finished turn and store only "
            "what future sessions need: memory_create for durable engineering "
            "facts, memory_candidate for uncertain ones, memory_update to correct "
            "existing memories. Never store the raw conversation."
        ),
        "tools": "memory",
        "mode": "write",
        "max_turns": 6,
        "reasoning_effort": "low",
    },
    "image-reader": {
        "name": "image-reader",
        "system_prompt": (
            "You read images for another agent. Given a screenshot and the "
            "ongoing conversation, answer the question about it precisely and "
            "briefly. Use the browser tools only if you need to look at more "
            "of the page, and never take actions."
        ),
        "tools": "browser",
        "mode": "read",
        "max_turns": 3,
        "reasoning_effort": "low",
    },
}


def _mode(body: dict) -> str:
    mode = (body.get("mode") or "read").strip().lower()
    if mode not in ("read", "write"):
        raise HTTPException(400, "mode must be 'read' or 'write'")
    return mode


def _effort(value) -> str | None:
    effort = str(value or "").strip().lower()
    if not effort:
        return None
    if effort not in REASONING_EFFORTS:
        raise HTTPException(
            400, f"reasoning_effort must be one of {', '.join(REASONING_EFFORTS)}"
        )
    return effort


@router.get("/presets")
def list_presets():
    return PRESETS


def _as_id(value) -> int | None:
    """Coerce a JSON body id to int (the web UI sends select values as strings)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.get("")
def list_agents(s: Session = Depends(session)):
    return s.exec(select(AgentConfig)).all()


@router.post("", status_code=201)
def create_agent(body: dict, s: Session = Depends(session)):
    for field in ("name", "provider_id"):
        if not body.get(field):
            raise HTTPException(400, f"{field} is required")
    if s.exec(select(AgentConfig).where(AgentConfig.name == body["name"])).first():
        raise HTTPException(409, f"agent profile already exists: {body['name']}")
    provider_id = _as_id(body.get("provider_id"))
    if provider_id is None or not s.get(Provider, provider_id):
        raise HTTPException(400, "provider not found")
    tools = body.get("tools", "repo,files")
    if isinstance(tools, list):
        tools = ",".join(tools)
    config = AgentConfig(
        name=body["name"],
        system_prompt=body.get("system_prompt", ""),
        provider_id=provider_id,
        model=(body.get("model") or "").strip() or None,
        reasoning_effort=_effort(body.get("reasoning_effort")),
        tools=tools,
        mode=_mode(body),
        max_turns=body.get("max_turns", 6),
    )
    s.add(config)
    s.commit()
    s.refresh(config)
    return config


@router.put("/{agent_id}")
def update_agent(agent_id: int, body: dict, s: Session = Depends(session)):
    config = s.get(AgentConfig, agent_id)
    if not config:
        raise HTTPException(404, "agent profile not found")
    if body.get("name"):
        config.name = body["name"]
    if "system_prompt" in body:
        config.system_prompt = body["system_prompt"] or ""
    if body.get("provider_id"):
        provider_id = _as_id(body.get("provider_id"))
        if provider_id is None or not s.get(Provider, provider_id):
            raise HTTPException(400, "provider not found")
        config.provider_id = provider_id
    if "model" in body:
        config.model = (body.get("model") or "").strip() or None
    if "reasoning_effort" in body:
        config.reasoning_effort = _effort(body.get("reasoning_effort"))
    if "tools" in body:
        tools = body["tools"]
        config.tools = ",".join(tools) if isinstance(tools, list) else tools
    if "mode" in body:
        config.mode = _mode(body)
    if body.get("max_turns"):
        config.max_turns = int(body["max_turns"])
    s.add(config)
    s.commit()
    s.refresh(config)
    return config


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, s: Session = Depends(session)):
    config = s.get(AgentConfig, agent_id)
    if not config:
        raise HTTPException(404, "agent profile not found")
    s.delete(config)
    s.commit()


@actions_router.get("")
def list_actions(s: Session = Depends(session)):
    defaults = action_defaults(s)
    return [{**a, "agent_id": defaults.get(a["key"])} for a in ACTIONS]


@actions_router.put("/{key}")
def set_action(key: str, body: dict, s: Session = Depends(session)):
    if key not in ACTIONS_BY_KEY:
        raise HTTPException(404, "unknown action")
    agent_id = _as_id(body.get("agent_id"))
    if agent_id is not None and not s.get(AgentConfig, agent_id):
        raise HTTPException(400, "agent profile not found")
    row = s.get(ActionDefault, key)
    if row is None:
        row = ActionDefault(action=key, agent_id=agent_id)
    else:
        row.agent_id = agent_id
    s.add(row)
    s.commit()
    return {"action": key, "agent_id": agent_id}
