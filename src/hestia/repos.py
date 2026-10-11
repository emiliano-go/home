"""Multi-repo helpers: the ProjectRepo rows behind a project.

Legacy single-repo columns on Project stay mirrored to the primary repo so
un-migrated code paths keep working; everything new goes through here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from sqlmodel import Session, select

from hestia import config, urls
from hestia.registry.models import Project, ProjectRepo

_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def repos_for(db: Session, project_id: int) -> list[ProjectRepo]:
    rows = db.exec(
        select(ProjectRepo)
        .where(ProjectRepo.project_id == project_id)
        .order_by(ProjectRepo.id)
    ).all()
    return sorted(rows, key=lambda r: (not r.is_primary, r.id or 0))


def primary(repos: list[ProjectRepo]) -> ProjectRepo | None:
    for repo in repos:
        if repo.is_primary:
            return repo
    return repos[0] if repos else None


def by_alias(repos: list[ProjectRepo], alias: str) -> ProjectRepo | None:
    return next((r for r in repos if r.alias == alias), None)


def memory_root(project) -> Path:
    """Where Totem lives: the primary clone, or the workspace when repo-less."""
    if getattr(project, "local_path", ""):
        return Path(project.local_path)
    return config.workspace_dir(project.name)


def sync_legacy(db: Session, project: Project, repos: list[ProjectRepo] | None = None) -> None:
    """Mirror the primary repo into the legacy Project columns."""
    rows = repos if repos is not None else repos_for(db, project.id)
    head = primary(rows)
    project.repo_url = head.repo_url if head else ""
    project.local_path = head.local_path if head else ""
    db.add(project)


def valid_alias(alias: str) -> bool:
    return bool(_ALIAS_RE.match(alias or ""))


def default_alias(url: str, taken: set[str]) -> str:
    slug = (url or "").rstrip("/").removesuffix(".git").split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug).strip("-")[:32]
    if not valid_alias(slug):
        slug = "repo"
    base, n = slug, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def clone_dir(project_name: str, alias: str) -> Path:
    return config.data_dir() / "repos" / config.slug(project_name) / alias


def auth_args(repo_url: str) -> list[str]:
    """git -c flags for authenticated GitHub HTTPS remotes (token from env or UI)."""
    token = config.github_token()
    if token and urls.github_host(repo_url):
        return ["-c", f"http.extraheader=Authorization: Bearer {token}"]
    return []


def clone(repo_url: str, dest: Path, timeout: int = 600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", *auth_args(repo_url), "clone", "--", repo_url, str(dest)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500] or "git clone failed")


def add_repo(db: Session, project: Project, alias: str, repo_url: str) -> ProjectRepo:
    alias = (alias or "").strip().lower()
    if not valid_alias(alias):
        raise ValueError("alias must be 1-32 chars: lowercase letters, digits, - or _")
    repo_url = (repo_url or "").strip()
    if not repo_url:
        raise ValueError("repo_url is required")
    existing = repos_for(db, project.id)
    if by_alias(existing, alias):
        raise ValueError(f"repo alias already exists: {alias}")
    dest = clone_dir(project.name, alias)
    if dest.exists():
        raise ValueError(f"clone directory already exists: {dest}")
    clone(repo_url, dest)
    repo = ProjectRepo(
        project_id=project.id,
        alias=alias,
        repo_url=repo_url,
        local_path=str(dest),
        is_primary=not existing,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    sync_legacy(db, project, existing + [repo])
    db.commit()
    return repo


def remove_repo(db: Session, project: Project, alias: str) -> None:
    repos = repos_for(db, project.id)
    repo = by_alias(repos, alias)
    if repo is None:
        raise ValueError(f"unknown repo alias: {alias}")
    remaining = [r for r in repos if r.alias != alias]
    db.delete(repo)
    if repo.is_primary and remaining:
        remaining[0].is_primary = True
        db.add(remaining[0])
    sync_legacy(db, project, remaining)
    db.commit()

    root = config.data_dir() / "repos" / config.slug(project.name)
    target = Path(repo.local_path)
    if not remaining:
        shutil.rmtree(root, ignore_errors=True)
    elif target.resolve() != root.resolve():
        # never delete a directory that still contains other repos
        shutil.rmtree(target, ignore_errors=True)
