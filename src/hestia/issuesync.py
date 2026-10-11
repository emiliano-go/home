"""Sync board tasks to GitHub issues (opt-in via Project.allow_git_writes).

Tasks carry a repo alias (None = primary); issues are created in that repo.
"""

from __future__ import annotations

import httpx
from sqlmodel import Session, select

from hestia import config, overview, repos
from hestia.registry.models import Project, Task

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = config.github_token()
    if not token:
        raise PermissionError("GITHUB_TOKEN is required to create issues")
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


def _create_issue(slug: str, payload: dict) -> dict:
    resp = httpx.post(
        f"{GITHUB_API}/repos/{slug}/issues", headers=_headers(), json=payload, timeout=30
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def sync_tasks(db: Session, project: Project, task_ids=None, repo: str | None = None) -> dict:
    if not project.allow_git_writes:
        raise PermissionError("enable git writes for this project to sync issues")
    rows = repos.repos_for(db, project.id)
    if not rows:
        raise ValueError("project has no repositories")
    by_alias = {r.alias: r for r in rows}
    primary = next((r for r in rows if r.is_primary), rows[0])
    if repo and repo not in by_alias:
        raise ValueError(f"unknown repo alias: {repo}")

    tasks = db.exec(select(Task).where(Task.project_id == project.id)).all()
    if task_ids:
        wanted = {int(i) for i in task_ids}
        tasks = [t for t in tasks if t.id in wanted]
    if repo:
        tasks = [t for t in tasks if (t.repo or primary.alias) == repo]

    created = []
    for task in tasks:
        if task.github_issue:
            continue
        alias = task.repo or primary.alias
        row = by_alias.get(alias)
        if row is None:
            raise ValueError(f"task #{task.id} targets unknown repo '{alias}'")
        slug = overview.repo_slug(row.repo_url)
        if not slug:
            raise ValueError(f"repo '{alias}' is not a GitHub repository")
        parts = [task.description or ""]
        if task.acceptance:
            parts.append(f"**Acceptance criteria**\n{task.acceptance}")
        parts.append(f"_Synced from the Hestia board (task #{task.id})._")
        issue = _create_issue(
            slug,
            {"title": task.title, "body": "\n\n".join(p for p in parts if p)},
        )
        task.github_issue = issue.get("number")
        task.repo = alias
        db.add(task)
        created.append(
            {
                "task_id": task.id,
                "repo": alias,
                "issue": task.github_issue,
                "url": issue.get("html_url"),
            }
        )
    db.commit()
    return {"created": created, "skipped": len(tasks) - len(created)}
