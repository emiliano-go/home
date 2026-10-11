"""Agent tools for the project kanban board.

These are bound to the registry DB (like the subagent tools), so the main chat
agent can list, create, move, edit, and delete tasks. Tasks are independent of
sessions, so the board outlives any conversation.
"""

from sqlmodel import Session, select

from hestia import milestones as milestones_mod
from hestia import taskboard
from hestia.registry.models import Milestone, Task
from hestia.tools.registry import ProjectContext, Tool, schema


def make_tools(db: Session) -> list[Tool]:
    def list_handler(ctx: ProjectContext, args: dict) -> list[dict]:
        query = select(Task).where(Task.project_id == ctx.project_id)
        if args.get("status"):
            query = query.where(Task.status == args["status"])
        tasks = db.exec(query.order_by(Task.position, Task.id)).all()
        blocked = taskboard.blocked_map(db, ctx.project_id)
        if args.get("ready"):
            tasks = [t for t in tasks if t.id not in blocked and t.status != "done"]
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "description": t.description,
                "milestone_id": t.milestone_id,
                "depends_on": taskboard.parse_depends(t.depends_on),
                "blocked_by": blocked.get(t.id, []),
                "due_at": t.due_at.isoformat() if t.due_at else None,
            }
            for t in tasks
        ]

    def create_handler(ctx: ProjectContext, args: dict) -> dict:
        task = taskboard.create(
            db,
            ctx.project_id,
            title=args.get("title", ""),
            description=args.get("description", ""),
            status=args.get("status", "backlog"),
            priority=args.get("priority", "medium"),
            milestone_id=args.get("milestone_id"),
            depends_on=args.get("depends_on"),
            acceptance=args.get("acceptance", ""),
            source=args.get("source", "user"),
            due_at=args.get("due_at"),
        )
        return taskboard.as_dict(task)

    def get_handler(ctx: ProjectContext, args: dict) -> dict:
        task = db.get(Task, args.get("id"))
        if task is None or task.project_id != ctx.project_id:
            raise ValueError(f"unknown task id: {args.get('id')}")
        blocked = taskboard.blocked_map(db, ctx.project_id)
        data = taskboard.as_dict(task, blocked.get(task.id))
        data["comments"] = [
            {
                "author": c.author,
                "body": c.body,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in taskboard.comments(db, task.id)
        ]
        return data

    def comment_handler(ctx: ProjectContext, args: dict) -> dict:
        task = db.get(Task, args.get("id"))
        if task is None or task.project_id != ctx.project_id:
            raise ValueError(f"unknown task id: {args.get('id')}")
        comment = taskboard.add_comment(
            db, task, args.get("body", ""), author=args.get("author") or "agent"
        )
        return {"id": comment.id, "author": comment.author, "body": comment.body}

    def update_handler(ctx: ProjectContext, args: dict) -> dict:
        task = db.get(Task, args.get("id"))
        if task is None or task.project_id != ctx.project_id:
            raise ValueError(f"unknown task id: {args.get('id')}")
        return taskboard.as_dict(taskboard.update(db, task, args))

    def delete_handler(ctx: ProjectContext, args: dict) -> dict:
        task = db.get(Task, args.get("id"))
        if task is None or task.project_id != ctx.project_id:
            raise ValueError(f"unknown task id: {args.get('id')}")
        taskboard.delete(db, task)
        return {"deleted": args.get("id")}

    def milestone_list_handler(ctx: ProjectContext, args: dict) -> list[dict]:
        items = db.exec(select(Milestone).where(Milestone.project_id == ctx.project_id)).all()
        return [milestones_mod.as_dict(m, milestones_mod.progress(db, m)) for m in items]

    def milestone_create_handler(ctx: ProjectContext, args: dict) -> dict:
        milestone = milestones_mod.create(
            db,
            ctx.project_id,
            title=args.get("title", ""),
            description=args.get("description", ""),
            target_date=args.get("target_date"),
        )
        return milestones_mod.as_dict(milestone)

    def milestone_update_handler(ctx: ProjectContext, args: dict) -> dict:
        milestone = db.get(Milestone, args.get("id"))
        if milestone is None or milestone.project_id != ctx.project_id:
            raise ValueError(f"unknown milestone id: {args.get('id')}")
        return milestones_mod.as_dict(milestones_mod.update(db, milestone, args))

    return [
        Tool(
            name="task_list",
            description=(
                "List the project's kanban tasks, optionally filtered by status. Each task "
                "includes depends_on and blocked_by (unmet dependency ids). Pass ready=true "
                "to get only unblocked, not-done tasks."
            ),
            parameters=schema(
                {
                    "status": {"type": "string", "enum": taskboard.STATUSES},
                    "ready": {"type": "boolean", "description": "only unblocked tasks"},
                },
                [],
            ),
            handler=list_handler,
            group="tasks",
        ),
        Tool(
            name="task_create",
            description=(
                "Create a task on the project kanban board. Use this to turn a plan "
                "or request into tracked work. Status defaults to 'backlog'."
            ),
            parameters=schema(
                {
                    "title": {"type": "string", "description": "short task title"},
                    "description": {"type": "string", "description": "optional detail"},
                    "status": {"type": "string", "enum": taskboard.STATUSES},
                    "priority": {"type": "string", "enum": taskboard.PRIORITIES},
                    "milestone_id": {
                        "type": "integer",
                        "description": "optional milestone to group this task under",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "task ids that must be done before this one can start",
                    },
                    "acceptance": {
                        "type": "string",
                        "description": "definition of done; required to confirm review before done",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["user", "suggested"],
                        "description": "use suggested when proposing work rather than doing it",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "optional deadline, ISO date (YYYY-MM-DD) or datetime",
                    },
                },
                ["title"],
            ),
            handler=create_handler,
            group="tasks",
        ),
        Tool(
            name="task_update",
            description=(
                "Update a task by id: rename, edit, change priority, or move it between "
                "columns (status: backlog, todo, doing, review, done)."
            ),
            parameters=schema(
                {
                    "id": {"type": "integer", "description": "task id (see task_list)"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": taskboard.STATUSES},
                    "priority": {"type": "string", "enum": taskboard.PRIORITIES},
                    "milestone_id": {"type": "integer", "description": "milestone id, or 0 to clear"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "replace the task's dependencies (empty list clears)",
                    },
                    "acceptance": {"type": "string", "description": "definition of done"},
                    "due_at": {
                        "type": "string",
                        "description": "deadline as ISO date or datetime; empty string clears it",
                    },
                    "pr_url": {
                        "type": "string",
                        "description": "pull request URL once the task has been implemented",
                    },
                    "reviewed": {
                        "type": "boolean",
                        "description": "confirm the review; required to move a task with acceptance criteria to done",
                    },
                },
                ["id"],
            ),
            handler=update_handler,
            group="tasks",
        ),
        Tool(
            name="task_get",
            description="Get one task by id with its dependencies, blocked_by, and comments.",
            parameters=schema({"id": {"type": "integer"}}, ["id"]),
            handler=get_handler,
            group="tasks",
        ),
        Tool(
            name="task_comment",
            description="Leave a note on a task card (visible to the owner and future sessions).",
            parameters=schema(
                {
                    "id": {"type": "integer"},
                    "body": {"type": "string"},
                    "author": {"type": "string", "description": "defaults to 'agent'"},
                },
                ["id", "body"],
            ),
            handler=comment_handler,
            group="tasks",
        ),
        Tool(
            name="task_delete",
            description="Delete a task from the board by id.",
            parameters=schema({"id": {"type": "integer"}}, ["id"]),
            handler=delete_handler,
            group="tasks",
        ),
        Tool(
            name="milestone_list",
            description="List the project's milestones (roadmap goals) with task progress.",
            parameters=schema({}, []),
            handler=milestone_list_handler,
            group="tasks",
        ),
        Tool(
            name="milestone_create",
            description=(
                "Create a milestone (roadmap goal) that groups tasks and tracks progress. "
                "Optionally give a target date (YYYY-MM-DD)."
            ),
            parameters=schema(
                {
                    "title": {"type": "string", "description": "short goal title"},
                    "description": {"type": "string", "description": "optional detail"},
                    "target_date": {"type": "string", "description": "target date YYYY-MM-DD"},
                },
                ["title"],
            ),
            handler=milestone_create_handler,
            group="tasks",
        ),
        Tool(
            name="milestone_update",
            description=(
                "Update a milestone by id: rename, edit, set a target date, or mark it "
                "open/done (status)."
            ),
            parameters=schema(
                {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "target_date": {"type": "string"},
                    "status": {"type": "string", "enum": milestones_mod.STATUSES},
                },
                ["id"],
            ),
            handler=milestone_update_handler,
            group="tasks",
        ),
    ]
