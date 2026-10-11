"""One-shot agent runs (docs, scheduled jobs): no chat session, just a prompt.

Triage and the memory fixer predate this and keep their own copies; new
server-side jobs share this helper.
"""

from sqlmodel import Session

from hestia import usage
from hestia.agent import loop as agent_loop
from hestia.providers.base import OpenAIClient, resolve_api_key
from hestia.tools import build_registry
from hestia.tools import tasks as task_tools
from hestia.tools.registry import ProjectContext


async def run_once(
    project,
    provider,
    system: str,
    user: str,
    groups: str = "",
    max_turns: int | None = None,
    tasks_db: Session | None = None,
    writes: bool = False,
    model: str | None = None,
    mode: str | None = None,
    write_allowlist: tuple[str, ...] | None = None,
) -> tuple[str, str | None, dict]:
    """Run one agent turn to completion.

    ``mode`` marks a delegated subagent run ("read" or "write"): the registry
    is capped to delegable groups and stripped of writes in read mode, and
    principal-only tools (images, task board, automations) are never added.
    ``writes`` is the project's allow_git_writes flag: in write mode it adds
    the repo edit tools, gated by the approval check through ``tasks_db``.

    Returns ``(final_text, error, token_usage)``.
    """
    ctx = ProjectContext.from_project(project)
    if write_allowlist:
        ctx.write_allowlist = tuple(write_allowlist)
    if mode is not None:
        from hestia.tools.subagents import delegated_registry

        registry = delegated_registry(groups, mode, writes=writes, db=tasks_db)
        if not registry.all():
            return "", f"no delegable tools (groups={groups!r}, mode={mode!r})", {}
    else:
        registry = build_registry(writes=writes)
        wanted = [g for g in (groups or "").split(",") if g]
        if wanted:
            registry = registry.filtered(wanted)
        if "images" in wanted:
            from hestia.tools import images as image_tools

            for tool in image_tools.make_tools(provider):
                registry.register(tool)
        if "browser" in wanted:
            from hestia.tools import browser as browser_tools

            if browser_tools.available():
                for tool in browser_tools.make_tools(provider, tasks_db):
                    registry.register(tool)
        if tasks_db is not None:
            from hestia.tools import jobs as job_tools
            from hestia.tools import preferences as pref_tools
            from hestia.tools import reminders as reminder_tools
            from hestia.tools import schedules as schedule_tools
            from hestia.tools import watches as watch_tools

            builders = {
                "tasks": task_tools.make_tools,
                "reminders": reminder_tools.make_tools,
                "watches": watch_tools.make_tools,
                "background": job_tools.make_tools,
                "automations": schedule_tools.make_tools,
                "memory": pref_tools.make_tools,
            }
            for group, builder in builders.items():
                if group in wanted:
                    for tool in builder(tasks_db):
                        registry.register(tool)
    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        model or provider.model,
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    final = ""
    tokens: dict = {}
    async for event in agent_loop.run_turn(
        ctx, client, registry, messages, max_turns=max_turns
    ):
        if event["type"] == "usage":
            usage.merge(tokens, event.get("usage"))
            continue
        if event["type"] == "message":
            final = event.get("content", "")
        elif event["type"] == "error":
            return final, event["message"], tokens
    return final, None, tokens
