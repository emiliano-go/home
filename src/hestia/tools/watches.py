"""Agent tools for watchers (page, feed, condition)."""

from sqlmodel import Session

from hestia import watchers
from hestia.registry.models import Watch
from hestia.tools.registry import ProjectContext, Tool, schema


def make_tools(db: Session) -> list[Tool]:
    def add_handler(ctx: ProjectContext, args: dict) -> dict:
        watch = watchers.create(
            db,
            kind=args.get("kind", "page"),
            url=args.get("url"),
            condition=args.get("condition", ""),
            interval_minutes=args.get("interval_minutes", 60),
            notify_on=args.get("notify_on", "change"),
            project_id=args.get("project_id") or ctx.project_id,
        )
        return watchers.as_dict(watch)

    def list_handler(ctx: ProjectContext, args: dict) -> list[dict]:
        return [watchers.as_dict(w) for w in watchers.list_all(db)]

    def cancel_handler(ctx: ProjectContext, args: dict) -> dict:
        watch = db.get(Watch, args.get("id"))
        if watch is None:
            raise ValueError(f"unknown watch id: {args.get('id')}")
        watchers.delete(db, watch)
        return {"deleted": args.get("id")}

    return [
        Tool(
            name="watch_add",
            description=(
                "Watch something and notify only when it happens. kind='page' notifies "
                "when the page text changes, or when the 'condition' phrase appears if "
                "notify_on='appear' (then it completes). kind='feed' notifies on new RSS "
                "or Atom items. kind='condition' runs a small check each interval and "
                "notifies when the condition is met, then completes. Interval is at "
                "least 30 minutes."
            ),
            parameters=schema(
                {
                    "kind": {"type": "string", "enum": watchers.KINDS},
                    "url": {"type": "string", "description": "page or feed URL"},
                    "condition": {
                        "type": "string",
                        "description": "phrase to look for (appear) or condition to check",
                    },
                    "interval_minutes": {"type": "integer", "minimum": watchers.MIN_INTERVAL},
                    "notify_on": {"type": "string", "enum": watchers.NOTIFY_ON},
                },
                ["kind"],
            ),
            handler=add_handler,
            group="chat",
        ),
        Tool(
            name="watch_list",
            description="List watchers with status and last result.",
            parameters=schema({}, []),
            handler=list_handler,
            group="chat",
        ),
        Tool(
            name="watch_cancel",
            description="Delete a watcher by id.",
            parameters=schema({"id": {"type": "integer"}}, ["id"]),
            handler=cancel_handler,
            group="chat",
        ),
    ]
