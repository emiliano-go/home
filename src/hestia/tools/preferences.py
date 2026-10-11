"""Agent tools for durable user memory.

The owner's name and standing preferences are injected into every system
prompt (see ``settings.prompt_context``), unlike project memory which is
retrieved by relevance. Use these for identity and rules the agent must never
forget: how to address the owner, tone, formatting, and response quirks.
"""

from sqlmodel import Session

from hestia import settings
from hestia.tools.registry import ProjectContext, Tool, schema


def make_tools(db: Session) -> list[Tool]:
    def remember_handler(ctx: ProjectContext, args: dict) -> dict:
        text = (args.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        return {"preferences": settings.add_preference(db, text)}

    def list_handler(ctx: ProjectContext, args: dict) -> dict:
        return {
            "user_name": settings.get(db, "user_name"),
            "preferences": settings.preferences(db),
        }

    def name_handler(ctx: ProjectContext, args: dict) -> dict:
        name = (args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        settings.set_many(db, {"user_name": name})
        return {"user_name": name}

    def forget_handler(ctx: ProjectContext, args: dict) -> dict:
        index = args.get("index")
        if index is None:
            raise ValueError("index is required (see list_preferences)")
        return {"preferences": settings.remove_preference(db, int(index))}

    return [
        Tool(
            name="set_owner_name",
            description=(
                "Remember the name the owner wants to be called (for example "
                "when they say 'call me Sam'). Injected as the owner's name in "
                "every future prompt."
            ),
            parameters=schema(
                {"name": {"type": "string", "description": "the name to use"}},
                ["name"],
            ),
            handler=name_handler,
            group="memory",
            effect="write",
        ),
        Tool(
            name="remember_preference",
            description=(
                "Save a durable global preference that is injected into every "
                "future prompt: how to respond, tone, formatting, things to "
                "avoid, or any rule the owner wants followed always. Use when "
                "the owner says to remember a rule or how they like things. "
                "Preferences are global, not per project."
            ),
            parameters=schema(
                {"text": {"type": "string", "description": "the rule, one sentence"}},
                ["text"],
            ),
            handler=remember_handler,
            group="memory",
            effect="write",
        ),
        Tool(
            name="list_preferences",
            description="List the owner's name and the durable global preferences.",
            parameters=schema({}, []),
            handler=list_handler,
            group="memory",
        ),
        Tool(
            name="forget_preference",
            description="Remove a global preference by its index (see list_preferences).",
            parameters=schema(
                {"index": {"type": "integer", "description": "0-based index"}},
                ["index"],
            ),
            handler=forget_handler,
            group="memory",
            effect="write",
        ),
    ]
