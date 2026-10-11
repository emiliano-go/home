"""Agent tool: push a notification to the owner (ntfy / Telegram)."""

from hestia import notify
from hestia.tools.registry import ProjectContext, Registry, Tool, schema


def register(registry: Registry) -> None:
    def handler(ctx: ProjectContext, args: dict) -> dict:
        title = (args.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")
        if not notify.configured():
            raise ValueError("no notification channel configured (set NTFY_TOPIC or TELEGRAM_BOT_TOKEN/CHAT_ID)")
        results = notify.send(
            title,
            args.get("message") or "",
            priority=args.get("priority") or "default",
            tags=args.get("tags") or [],
        )
        failed = [name for name, r in results.items() if not r.get("ok")]
        if failed and len(failed) == len(results):
            raise RuntimeError(f"notification failed: {results[failed[0]].get('error')}")
        return results

    registry.register(Tool(
        name="notify",
        description=(
            "Send the owner a push notification (ntfy/Telegram). Use it for things "
            "worth interrupting them: a finished long job, a blocked task, a CI "
            "failure that needs attention. Not for routine progress."
        ),
        parameters=schema(
            {
                "title": {"type": "string", "description": "short headline"},
                "message": {"type": "string", "description": "one or two sentences"},
                "priority": {
                    "type": "string",
                    "enum": ["min", "low", "default", "high", "urgent"],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ntfy tags/emoji shortcodes, e.g. ['warning']",
                },
            },
            ["title"],
        ),
        handler=handler,
        group="notify",
        effect="write",
    ))
