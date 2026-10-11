"""Implement a board task: run the agent on a branch and open a PR.

The run is submitted as a background job so the request returns immediately;
the agent moves the task to review and records the PR URL when done.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hestia import jobs, taskboard
from hestia.registry.db import session
from hestia.registry.models import Project, Task

router = APIRouter(prefix="/api", tags=["implement"])


def _brief(task: Task, blocked_by: list[int]) -> str:
    lines = [
        f"Implement this task from the project board.",
        "",
        f"## Task #{task.id}: {task.title}",
        task.description or "(no description)",
    ]
    if task.acceptance:
        lines += ["", f"Acceptance criteria: {task.acceptance}"]
    if blocked_by:
        lines += ["", f"Note: blocked by task {blocked_by} (should be done)."]
    if task.repo:
        lines += [
            "",
            f'Repository: {task.repo} (pass repo="{task.repo}" to git/file tools).',
        ]
    lines += [
        "",
        "Work on a new branch, make focused commits, push, and open a pull",
        "request. Do not force-push. When done, call task_update to set pr_url",
        "and move the task to review, and leave a task_comment summarizing the",
        "change.",
    ]
    return "\n".join(lines)


def _submit(db: Session, project: Project, task: Task) -> dict:
    if not project.allow_git_writes:
        raise HTTPException(403, "git writes are disabled for this project")
    if project.require_write_approval:
        raise HTTPException(
            403, "this project requires write approval; approve a request first"
        )
    if task.status == "done":
        raise HTTPException(400, "task is already done")
    blocked = taskboard.blocked_map(db, project.id).get(task.id, [])
    job_id = jobs.submit(
        project_id=project.id,
        session_id=None,
        kind="agent",
        instruction=_brief(task, blocked),
        description=f"Implement #{task.id} {task.title}"[:80],
        action="implement",
    )
    taskboard.update(db, task, {"status": "doing"})
    return {"job_id": job_id, "task_id": task.id, "status": "queued"}


@router.post("/tasks/{task_id}/implement")
def implement_task(task_id: int, s: Session = Depends(session)):
    task = s.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    project = s.get(Project, task.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return _submit(s, project, task)


@router.post("/projects/{project_id}/tasks/run-next")
def run_next(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    task = taskboard.next_ready(s, project_id)
    if task is None:
        raise HTTPException(400, "no ready task to run")
    return _submit(s, project, task)
