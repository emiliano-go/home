"""Inbox: GitHub polling into a notification table (PRs, issues, CI failures).

The first poll for a project is a silent baseline (existing items arrive
already read) so enabling the poller does not flood the inbox.
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from hestia import events, notify, overview, repos
from hestia.registry.models import InboxItem, Project

_KINDS = ("pr", "issue", "run")

_EVENT_KIND = {"run": "ci_failure", "pr": "pr_opened", "issue": "issue_opened"}


def _has_items(db: Session, project_id: int) -> bool:
    return (
        db.exec(select(InboxItem).where(InboxItem.project_id == project_id)).first()
        is not None
    )


def _add(
    db: Session,
    project_id: int,
    kind: str,
    external_id: str,
    title: str,
    subtitle: str,
    url: str | None,
    baseline: bool,
    repo: str = "",
) -> InboxItem | None:
    exists = db.exec(
        select(InboxItem).where(
            InboxItem.project_id == project_id,
            InboxItem.kind == kind,
            InboxItem.external_id == external_id,
        )
    ).first()
    if exists:
        return None
    item = InboxItem(
        project_id=project_id,
        kind=kind,
        external_id=external_id,
        repo=repo,
        title=title,
        subtitle=subtitle,
        url=url,
        read=baseline,
    )
    db.add(item)
    return item


def _notify_new_items(project: Project, items: list[InboxItem]) -> None:
    if not notify.configured():
        return
    lines = "\n".join(f"- {i.title} ({i.subtitle})" for i in items[:5])
    if len(items) > 5:
        lines += f"\n- ...and {len(items) - 5} more"
    notify.send(
        f"{len(items)} new in {project.name}",
        lines,
        tags=["inbox_tray"],
        url=items[0].url,
    )


def poll_project(db: Session, project: Project) -> tuple[int, list[InboxItem]]:
    """Fetch open PRs/issues and failing runs from every repo; insert unseen ones.

    Returns (created count, newly added unread items).
    """
    rows = repos.repos_for(db, project.id)
    if not rows:
        return 0, []
    multi = len(rows) > 1
    baseline = not _has_items(db, project.id)
    created = 0
    new_unread: list[InboxItem] = []

    def track(item: InboxItem | None) -> None:
        nonlocal created
        if item is None:
            return
        created += 1
        if not item.read:
            new_unread.append(item)
            events.emit(
                db,
                project.id,
                _EVENT_KIND.get(item.kind, item.kind),
                {"title": item.title, "url": item.url, "text": item.subtitle},
                key=item.external_id,
            )

    for row in rows:
        if not overview.repo_slug(row.repo_url):
            continue
        prs = overview.github_list_for_url(row.repo_url, "prs", state="open", limit=30)
        if not prs.get("available"):
            continue
        issues = overview.github_list_for_url(row.repo_url, "issues", state="open", limit=30)
        runs = overview.github_list_for_url(row.repo_url, "runs", limit=15)
        prefix = f"{row.alias}:" if multi else ""
        suffix = f" · {row.alias}" if multi else ""
        for pr in prs.get("items", []):
            track(
                _add(
                    db,
                    project.id,
                    "pr",
                    f"{prefix}pr:{pr['number']}",
                    f"#{pr['number']} {pr['title']}",
                    f"Pull request · {pr.get('user') or 'unknown'}{suffix}",
                    pr.get("url"),
                    baseline,
                    row.alias,
                )
            )
        for issue in issues.get("items", []):
            track(
                _add(
                    db,
                    project.id,
                    "issue",
                    f"{prefix}issue:{issue['number']}",
                    f"#{issue['number']} {issue['title']}",
                    f"Issue · {issue.get('user') or 'unknown'}{suffix}",
                    issue.get("url"),
                    baseline,
                    row.alias,
                )
            )
        for run in runs.get("items", []):
            if run.get("conclusion") != "failure":
                continue
            track(
                _add(
                    db,
                    project.id,
                    "run",
                    f"{prefix}run:{run.get('id')}",
                    run.get("name") or "CI run",
                    f"CI failure{suffix}",
                    run.get("url"),
                    baseline,
                    row.alias,
                )
            )
    if created:
        db.commit()
    return created, new_unread


def poll_all(db: Session) -> int:
    total = 0
    for project in db.exec(select(Project)).all():
        try:
            created, new_unread = poll_project(db, project)
        except Exception:
            continue  # one unreachable repo must not stop the rest
        total += created
        if new_unread:
            _notify_new_items(project, new_unread)
    total += check_pulls(db)
    return total


def check_pulls(db: Session) -> int:
    """Surface a "Pull pending" inbox item per repo behind its remote.

    Fetches first, so it reflects the real remote state. Items are removed
    once the clone catches up (or after a pull).
    """
    count = 0
    for project in db.exec(select(Project)).all():
        rows = repos.repos_for(db, project.id)
        multi = len(rows) > 1
        active: set[str] = set()
        for row in rows:
            ext = f"pull:{row.alias}" if multi else "pull"
            try:
                pending = overview.pending_pull(Path(row.local_path), do_fetch=True)
            except Exception:
                pending = None  # missing path, no upstream, no network
            item = db.exec(
                select(InboxItem).where(
                    InboxItem.project_id == project.id,
                    InboxItem.kind == "pull",
                    InboxItem.external_id == ext,
                )
            ).first()
            if pending:
                active.add(ext)
                subtitle = f"{pending['behind']} commit(s) behind origin/{pending['branch']}"
                if multi:
                    subtitle = f"{row.alias}: {subtitle}"
                if item is None:
                    item = InboxItem(
                        project_id=project.id,
                        kind="pull",
                        external_id=ext,
                        repo=row.alias,
                        title="Pull pending",
                        subtitle=subtitle,
                        read=False,
                    )
                    db.add(item)
                    db.commit()
                    db.refresh(item)
                    count += 1
                    label = f"{project.name} · {row.alias}" if multi else project.name
                    notify.send(f"Pull pending · {label}", subtitle, tags=["arrow_down"])
                elif item.subtitle != subtitle:
                    item.subtitle = subtitle
                    db.add(item)
                    db.commit()
        # drop stale pull items (repo removed, or clone caught up)
        for item in db.exec(
            select(InboxItem).where(
                InboxItem.project_id == project.id, InboxItem.kind == "pull"
            )
        ).all():
            if item.external_id not in active:
                db.delete(item)
                db.commit()
    return count


def list_items(db: Session, unread_only: bool = False) -> dict:
    query = select(InboxItem).order_by(InboxItem.created_at.desc(), InboxItem.id.desc())
    if unread_only:
        query = query.where(InboxItem.read == False)  # noqa: E712
    items = db.exec(query.limit(100)).all()
    names = {p.id: p.name for p in db.exec(select(Project)).all()}
    unread = len(
        db.exec(select(InboxItem).where(InboxItem.read == False)).all()  # noqa: E712
    )
    return {
        "unread": unread,
        "items": [
            {
                "id": i.id,
                "project_id": i.project_id,
                "project": names.get(i.project_id, ""),
                "kind": i.kind,
                "external_id": i.external_id,
                "title": i.title,
                "subtitle": i.subtitle,
                "url": i.url,
                "read": i.read,
                "created_at": overview._iso(i.created_at),
            }
            for i in items
        ],
    }
