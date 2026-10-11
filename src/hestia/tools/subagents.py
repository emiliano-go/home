"""Subagent spawning: the main agent can delegate to named agent profiles.

Each AgentConfig has its own provider (any OpenAI-compatible model), system
prompt, and tool subset, so cheap models can run exploration while the main
agent reasons with a stronger one.

Delegation has two modes, enforced here for foreground and background runs:
read (exploration, scanning, review: no writes at all) and write (workspace
files, project memory, and file edits in the clone when the project has git
writes enabled, for cheap bulk work like doc sweeps, renames, and typo
fixes). Subagents can never run mutating git commands (branch/commit/push/PR)
or use principal-only capabilities (images, task board, automations,
notifications, delegation itself); the principal commits and opens PRs after
review. Subagents never get the agents group, so they cannot spawn further
subagents.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from sqlmodel import Session, select

from hestia import actions, runs, usage
from hestia.agent import loop as agent_loop
from hestia.agent.prompt import POLICY
from hestia.providers.base import provider_client, resolve_api_key
from hestia.registry.models import AgentConfig, Provider
from hestia.tools import build_registry
from hestia.tools.registry import ProjectContext, Registry, Tool, schema

DELEGABLE_GROUPS = (
    "repo",
    "files",
    "github",
    "web",
    "skills",
    "memory",
    "workspace",
    "writes",
)

SUBAGENT_PROMPT = """\
You are a subagent of a project cockpit agent. Complete the task below and
return a concise, self-contained summary of your findings (plain text, no
questions back).

## Policy
""" + POLICY

READONLY_NOTE = """\
## Read-only mode (overrides the policy above)
This run has read-only tools: you cannot write files, the workspace, or
memory. Investigate, inspect, and report only.
"""

WRITE_NOTE = """\
## Write mode
You may write workspace files and project memory. When git writes are enabled
you may also edit repository files with write_file. You cannot run mutating
git commands: the principal agent handles branches, commits, pushes, and pull
requests after reviewing your changes.
"""


def delegated_registry(
    groups: str, mode: str = "read", writes: bool = False, db=None
) -> Registry:
    """The only registry a subagent ever gets: delegable groups, read-only in read mode.

    Principal-only groups (images, tasks, agents, automations, ...) and
    principal-only tools (git branch/commit/push/PR) are stripped even when a
    profile lists them. ``writes`` is the project's allow_git_writes flag: in
    write mode it adds file editing in the clone; git mutations stay with the
    principal.
    """
    wanted = [g.strip() for g in (groups or "").split(",") if g.strip()]
    allowed = [g for g in wanted if g in DELEGABLE_GROUPS]
    registry = build_registry()
    if writes:
        from hestia.tools import gitwrites

        gitwrites.register(registry, db)
    registry = registry.filtered(allowed).delegable()
    return registry.readonly() if (mode or "read") == "read" else registry


def subagent_system(config: AgentConfig) -> str:
    note = READONLY_NOTE if (config.mode or "read") == "read" else WRITE_NOTE
    return f"{SUBAGENT_PROMPT}\n{note}\n## Agent instructions\n{config.system_prompt}"


def _parent_event(ctx: ProjectContext, event: dict) -> None:
    """Forward a subagent/swarm lifecycle event to the parent chat run."""
    if not ctx.run_id:
        return
    parent = runs.manager.get(ctx.run_id)
    if parent is not None:
        runs.manager.emit(parent, event)


def _resolve_config(db: Session, action: str | None, agent: str | None) -> AgentConfig | None:
    config = actions.resolve_action(db, action) if action else None
    if config is None and agent:
        config = db.exec(select(AgentConfig).where(AgentConfig.name == agent)).first()
    return config


def _spawn(
    ctx: ProjectContext,
    db: Session,
    config: AgentConfig,
    task: str,
    *,
    directive: str = "",
    write_scope: list[str] | None = None,
    index: int | None = None,
) -> dict:
    """Run one delegated subagent to completion and report its child run."""
    provider = db.get(Provider, config.provider_id)
    if provider is None:
        raise ValueError(f"agent profile '{config.name}' has no valid provider")
    provider = actions.effective_provider(config, provider)
    client = provider_client(
        provider,
        provider.model,
        db=db,
        session=f"subagent-{ctx.session_id or ctx.project_id}",
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    registry = delegated_registry(config.tools, config.mode, writes=ctx.allow_git_writes, db=db)
    if not registry.all():
        raise ValueError(
            f"agent profile '{config.name}' has no delegable tools "
            f"(tools={config.tools!r}, mode={config.mode!r})"
        )
    system = subagent_system(config)
    if directive:
        system += f"\n\n## Swarm directive\n{directive}"
    child = runs.manager.create(
        "subagent",
        project_id=ctx.project_id,
        session_id=ctx.session_id,
        parent_run_id=ctx.run_id,
        title=task[:120],
    )
    _parent_event(ctx, {
        "type": "subagent", "tool_call_id": ctx.tool_call_id, "run_id": child.id,
        "index": index, "name": config.name, "title": task[:80], "status": "running",
    })
    sub_ctx = replace(
        ctx,
        write_allowlist=tuple(write_scope) if write_scope else ctx.write_allowlist,
    )
    result = _run_subagent_in_thread(
        sub_ctx, client, registry,
        [{"role": "system", "content": system}, {"role": "user", "content": task}],
        child,
        max_turns=config.max_turns,
    )
    tokens = result.get("tokens") or {}
    if tokens:
        try:
            usage.record(db, ctx.project_id, session_id=ctx.session_id,
                         action="subagent", model=provider.model, usage=tokens)
        except Exception:
            pass
    error = result.get("error")
    out = {
        "index": index, "agent": config.name, "task": task, "run_id": child.id,
        "status": "error" if error else "done",
        "summary": result.get("summary", ""), "error": error or "",
    }
    _parent_event(ctx, {
        "type": "subagent", "tool_call_id": ctx.tool_call_id, "run_id": child.id,
        "index": index, "name": config.name, "status": out["status"],
        "summary": (out["summary"] or out["error"])[:2000],
    })
    return out


def run_swarm(
    ctx: ProjectContext,
    db: Session,
    directive: str,
    tasks: list,
    max_parallel: int = 3,
    write_scope: list[str] | None = None,
) -> list[dict]:
    """Fan out a shared directive to several subagents, each with its own task."""
    if not tasks:
        raise ValueError("tasks must be a non-empty list")
    specs = []
    for i, item in enumerate(tasks):
        if not isinstance(item, dict) or not str(item.get("task") or "").strip():
            raise ValueError(f"task {i} needs a 'task' string")
        action = item.get("action") or ("explore" if not item.get("agent") else None)
        config = _resolve_config(db, action, item.get("agent"))
        if config is None:
            raise ValueError(f"task {i}: unknown agent/action {item.get('action') or item.get('agent')}")
        specs.append((i, str(item["task"]).strip(), config))
    workers = max(1, min(int(max_parallel or 3), len(specs)))
    out: list = [None] * len(specs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_spawn, ctx, db, config, task,
                        directive=directive, write_scope=write_scope, index=i): i
            for (i, task, config) in specs
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                out[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                out[i] = {"index": i, "status": "error", "error": f"{type(e).__name__}: {e}"}
    return out


def make_tools(db: Session) -> list[Tool]:
    def run_handler(ctx: ProjectContext, args: dict) -> dict:
        config = None
        if args.get("action"):
            config = actions.resolve_action(db, args["action"])
        if config is None and args.get("agent"):
            config = db.exec(select(AgentConfig).where(AgentConfig.name == args["agent"])).first()
        if config is None:
            raise ValueError(
                f"unknown agent profile or action: {args.get('action') or args.get('agent')}"
            )
        write_scope = [str(g).strip() for g in (args.get("write_scope") or []) if str(g).strip()]
        if args.get("run_in_background"):
            from hestia import jobs

            key = args.get("action") or args.get("agent") or config.name
            job_id = jobs.submit(
                project_id=ctx.project_id,
                session_id=ctx.session_id,
                kind="subagent",
                instruction=args["task"],
                description=args.get("description") or args["task"][:60],
                action=key,
                payload=json.dumps({"agent": config.name, "write_scope": write_scope or None}),
            )
            return {
                "job_id": job_id,
                "status": "queued",
                "note": "Subagent running in the background; you will be notified when it finishes.",
            }
        result = _spawn(ctx, db, config, args["task"], write_scope=write_scope or None)
        if result.get("error"):
            raise RuntimeError(result["error"])
        return {"summary": result["summary"], "run_id": result["run_id"], "status": result["status"]}

    def swarm_handler(ctx: ProjectContext, args: dict) -> dict:
        directive = str(args.get("directive") or "").strip()
        tasks = args.get("tasks") or []
        if not directive:
            raise ValueError("directive is required")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
            raise ValueError("tasks must be a list of 1 to 8 items")
        write_scope = [str(g).strip() for g in (args.get("write_scope") or []) if str(g).strip()]
        parallel = int(args.get("max_parallel") or 3)
        if args.get("run_in_background"):
            from hestia import jobs

            job_id = jobs.submit(
                project_id=ctx.project_id,
                session_id=ctx.session_id,
                kind="swarm",
                instruction=directive,
                description=args.get("description") or directive[:60],
                action="swarm",
                payload=json.dumps({
                    "directive": directive,
                    "tasks": tasks,
                    "max_parallel": parallel,
                    "write_scope": write_scope or None,
                }),
            )
            return {
                "job_id": job_id,
                "count": len(tasks),
                "status": "queued",
                "note": "Swarm running in the background; you will be notified when it finishes.",
            }
        results = run_swarm(ctx, db, directive, tasks, parallel, write_scope or None)
        return {"count": len(results), "results": results}

    def list_handler(ctx: ProjectContext, args: dict) -> list[dict]:
        configs = db.exec(select(AgentConfig)).all()
        return [
            {
                "name": c.name,
                "tools": c.tools,
                "mode": c.mode,
                "max_turns": c.max_turns,
                "provider_id": c.provider_id,
            }
            for c in configs
        ]

    return [
        Tool(
            name="run_subagent",
            description=(
                "Delegate a subtask to a specialised agent: read mode for "
                "exploration, scanning, and review, write mode for workspace "
                "deliverables, memory curation, and bulk file edits in the "
                "clone (doc sweeps, renames, typo fixes) with a cheap model. "
                "Pass an 'action' (the configured role: explore, github-scan, "
                "memory-keeper, writer, code-reviewer, bulk-edit) so the app "
                "uses the agent assigned to it, or a specific 'agent' profile "
                "name (see agent_list). Subagents can edit files but never "
                "branch, commit, push, or open PRs; those are yours."
            ),
            parameters=schema({
                "action": {
                    "type": "string",
                    "description": "configured action/role for the subtask (preferred)",
                    "enum": [
                        "explore",
                        "github-scan",
                        "memory-keeper",
                        "writer",
                        "code-reviewer",
                        "bulk-edit",
                    ],
                },
                "agent": {"type": "string", "description": "agent profile name (see agent_list)"},
                "task": {"type": "string", "description": "self-contained task for the subagent"},
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "run the subagent detached and return a job id now; you "
                        "will be notified when it finishes"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "short 3 to 5 word label (required with run_in_background)",
                },
                "write_scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "optional repo/workspace globs the subagent may write "
                        "(e.g. ['src/foo/**']); omit for no restriction"
                    ),
                },
            }, ["task"]),
            handler=run_handler,
            group="agents",
        ),
        Tool(
            name="run_swarm",
            description=(
                "Fan out one main directive to several subagents in parallel, each "
                "with its own specific task (e.g. directive 'audit the codebase', "
                "tasks ['agent A audits src/x.py', 'agent B audits src/y.py']). "
                "Returns per-agent status, run id, and summary. Subagents can never "
                "branch/commit/push; you do that after reviewing their work."
            ),
            parameters=schema({
                "directive": {
                    "type": "string",
                    "description": "the shared main directive every subagent receives",
                },
                "tasks": {
                    "type": "array",
                    "description": "1 to 8 specific tasks",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "this agent's specific task"},
                            "action": {
                                "type": "string",
                                "description": "configured role (default explore)",
                            },
                            "agent": {"type": "string", "description": "agent profile name"},
                        },
                        "required": ["task"],
                    },
                },
                "max_parallel": {
                    "type": "integer",
                    "description": "how many subagents run at once (default 3)",
                },
                "write_scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "optional globs the write-mode subagents may write",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "detach the whole swarm and get a job id + notification",
                },
                "description": {
                    "type": "string",
                    "description": "short label (with run_in_background)",
                },
            }, ["directive", "tasks"]),
            handler=swarm_handler,
            group="agents",
            delegable=False,
        ),
        Tool(
            name="agent_list",
            description="List available subagent profiles (name, mode, tool groups, provider).",
            parameters=schema({}, []),
            handler=list_handler,
            group="agents",
        ),
    ]


def _progress(parent_run, tool_call_id: str | None, text: str) -> None:
    """Forward a child run's step into the parent tool row."""
    if not parent_run or not tool_call_id:
        return
    runs.manager.emit(
        parent_run,
        {"type": "tool_progress", "tool_call_id": tool_call_id, "text": text[:160]},
    )


async def _run_subagent(ctx, client, registry, messages, run=None, max_turns=None) -> dict:
    final = ""
    status, error = "done", ""
    parent = runs.manager.get(ctx.run_id) if ctx.run_id else None
    steps = 0
    tokens: dict = {}
    try:
        async for event in agent_loop.run_turn(
            ctx, client, registry, messages, run=run, max_turns=max_turns
        ):
            if run is not None:
                runs.manager.emit(run, event)
            etype = event["type"]
            if etype == "usage":
                usage.merge(tokens, event.get("usage"))
                continue
            if etype == "tool_call":
                steps += 1
                _progress(parent, ctx.tool_call_id, f"step {steps} · {event.get('name')}")
            elif etype == "thinking" and event.get("text"):
                _progress(parent, ctx.tool_call_id, event["text"].strip().splitlines()[-1][:120])
            elif etype == "message":
                final = event.get("content", "") or final
            elif etype in ("error", "stopped", "timed_out"):
                status, error = etype, event.get("message", "")
    finally:
        if run is not None:
            runs.manager.finish(run, status, result=final, error=error)
    if error:
        return {"error": error, "tokens": tokens}
    return {"summary": final, "tokens": tokens}


def _run_subagent_in_thread(ctx, client, registry, messages, run=None, max_turns=None) -> dict:
    """Run the subagent loop off the main event loop.

    Tool handlers are sync, so this is called from inside the parent's running
    loop; asyncio.run needs its own thread. Subagent tools never touch the
    request DB session, so crossing threads here is safe.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, _run_subagent(ctx, client, registry, messages, run, max_turns)
        ).result()
