"""Agent tools for project goals (discussion + spec objects)."""

from sqlmodel import Session, select

from hestia import goals
from hestia.registry.models import Goal
from hestia.tools.registry import ProjectContext, Tool, schema


def make_tools(db: Session) -> list[Tool]:
    def list_handler(ctx: ProjectContext, args: dict) -> list[dict]:
        rows = db.exec(select(Goal).where(Goal.project_id == ctx.project_id)).all()
        return [goals.as_dict(g, goals.progress(db, g)) for g in rows]

    def create_handler(ctx: ProjectContext, args: dict) -> dict:
        goal = goals.create(
            db,
            ctx.project_id,
            title=args.get("title", ""),
            description=args.get("description", ""),
            success_criteria=args.get("success_criteria", ""),
        )
        return goals.as_dict(goal)

    def update_handler(ctx: ProjectContext, args: dict) -> dict:
        goal = db.get(Goal, args.get("id"))
        if goal is None or goal.project_id != ctx.project_id:
            raise ValueError(f"unknown goal id: {args.get('id')}")
        return goals.as_dict(goals.update(db, goal, args), goals.progress(db, goal))

    return [
        Tool(
            name="goal_list",
            description="List the project's goals with status and board progress.",
            parameters=schema({}, []),
            handler=list_handler,
            group="tasks",
        ),
        Tool(
            name="goal_create",
            description=(
                "Create a project goal (a discussed outcome with a spec). Use this when "
                "the user states a substantial outcome; planning it into tasks happens "
                "from the Goals tab."
            ),
            parameters=schema(
                {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "success_criteria": {"type": "string"},
                },
                ["title"],
            ),
            handler=create_handler,
            group="tasks",
        ),
        Tool(
            name="goal_update",
            description="Update a goal by id: title, description, success_criteria, or status (drafting, active, done, dropped).",
            parameters=schema(
                {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "success_criteria": {"type": "string"},
                    "status": {"type": "string", "enum": goals.STATUSES},
                },
                ["id"],
            ),
            handler=update_handler,
            group="tasks",
        ),
    ]
