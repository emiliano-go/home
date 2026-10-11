"""Mutating git tools, gated behind ``Project.allow_git_writes``.

These are registered into a project's agent registry only when the owner
explicitly opts in. All paths are sandboxed to the clone and ``.git`` is off
limits. Commits are authored as "Hestia Agent"; pushes to GitHub use
``GITHUB_TOKEN`` when present.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlmodel import Session, select

from hestia import config, overview, urls
from hestia import memory_autoreg
from hestia.tools.registry import ProjectContext, Registry, Tool, schema, write_allowed

GITHUB_API = "https://api.github.com"
_MAX_WRITE_BYTES = 1_000_000

_AUTHOR = [
    "-c",
    "user.name=Hestia Agent",
    "-c",
    "user.email=hestia@localhost",
    "-c",
    "commit.gpgsign=false",  # agent commits are unsigned; no GPG agent headless
]


def _git(
    ctx: ProjectContext,
    args: list[str],
    timeout: int = 120,
    extra: list[str] | None = None,
    repo: str | None = None,
) -> str:
    result = subprocess.run(
        ["git", *(extra or []), *args],
        cwd=ctx.repo_path(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:2000] or "git command failed")
    return result.stdout.strip()


def _resolve(ctx: ProjectContext, rel: str, repo: str | None = None) -> Path:
    root = ctx.repo_path(repo).resolve()
    path = (root / rel).resolve()
    if path != root and not str(path).startswith(str(root) + os.sep):
        raise PermissionError(f"path escapes the repository: {rel}")
    parts = path.relative_to(root).parts
    if ".git" in parts or ".totem" in parts or ".hestia" in parts:
        raise PermissionError("refusing to touch Hestia's metadata (.git, .totem, .hestia)")
    return path


def _write_file(ctx: ProjectContext, args: dict) -> dict:
    rel = (args.get("path") or "").strip()
    if not rel:
        raise ValueError("path is required")
    content = args.get("content") or ""
    if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
        raise ValueError(f"content exceeds {_MAX_WRITE_BYTES} bytes")
    repo = args.get("repo")
    if not write_allowed(ctx, rel):
        raise PermissionError(
            f"write scope: {rel} is outside the allowed files {ctx.write_allowlist}"
        )
    path = _resolve(ctx, rel, repo)
    if path.is_dir():
        raise ValueError(f"path is a directory: {rel}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    memory_autoreg.record(ctx.memory_path, path, "wrote")
    return {
        "path": str(path.relative_to(ctx.repo_path(repo).resolve())),
        "repo": ctx.repo(repo).alias,
        "bytes": len(content.encode("utf-8")),
    }


def _create_branch(ctx: ProjectContext, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    repo = args.get("repo")
    check = subprocess.run(
        ["git", "check-ref-format", "--branch", name],
        cwd=ctx.repo_path(repo),
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise ValueError(f"invalid branch name: {name}")
    _git(ctx, ["checkout", "-b", name], repo=repo)
    return {"branch": name, "repo": ctx.repo(repo).alias}


def _commit(ctx: ProjectContext, args: dict) -> dict:
    message = (args.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    repo = args.get("repo")
    paths = args.get("paths") or []
    if paths:
        resolved = [
            str(_resolve(ctx, p, repo).relative_to(ctx.repo_path(repo).resolve()))
            for p in paths
        ]
        _git(ctx, ["add", "--", *resolved], repo=repo)
    else:
        _git(ctx, ["add", "-A", "--", ".", ":!.totem"], repo=repo)
    staged = _git(ctx, ["diff", "--cached", "--name-only"], repo=repo)
    if not staged:
        raise ValueError("nothing to commit")
    _git(ctx, ["commit", "-m", message], extra=_AUTHOR, repo=repo)
    return {
        "repo": ctx.repo(repo).alias,
        "sha": _git(ctx, ["rev-parse", "HEAD"], repo=repo),
        "summary": _git(ctx, ["log", "-1", "--oneline"], repo=repo),
        "files": staged.splitlines(),
    }


def _require_approval(db, ctx: ProjectContext, action: str) -> None:
    """Hard gate for opted-in projects: a fresh approved request is required.

    # ponytail: one approval covers a 30 minute window and any number of calls
    in it; per-call consumption if that ever matters.
    """
    if db is None:
        return
    from hestia.registry.models import Project, Question

    project = db.get(Project, ctx.project_id)
    if project is None:
        return
    asks = bool(getattr(project, "require_write_approval", False)) or ctx.write_mode == "ask"
    if not asks:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    rows = db.exec(
        select(Question)
        .where(
            Question.project_id == ctx.project_id,
            Question.kind == "approval",
            Question.status == "answered",
        )
        .order_by(Question.id.desc())
    ).all()
    for question in rows:
        try:
            meta = json.loads(question.meta or "{}")
        except ValueError:
            meta = {}
        if meta.get("action") != action:
            continue
        if (question.answer or "").strip().lower() not in ("approve", "approved"):
            continue
        answered = question.answered_at or question.created_at
        if answered is None:
            continue
        if answered.tzinfo is None:
            answered = answered.replace(tzinfo=timezone.utc)
        if answered >= cutoff:
            return
    raise PermissionError(
        f"{action} requires your approval first: call ask_approval and wait for the answer"
    )


def _push(ctx: ProjectContext, args: dict, db: Session | None = None) -> dict:
    _require_approval(db, ctx, "git_push")
    repo = args.get("repo")
    branch = (args.get("branch") or "").strip() or _git(
        ctx, ["rev-parse", "--abbrev-ref", "HEAD"], repo=repo
    )
    extra: list[str] = []
    token = config.github_token()
    if token and urls.github_host(ctx.repo_url_for(repo)):
        extra = ["-c", f"http.extraheader=Authorization: Bearer {token}"]
    output = _git(ctx, ["push", "-u", "origin", branch], extra=extra, timeout=300, repo=repo)
    return {"branch": branch, "repo": ctx.repo(repo).alias, "output": output[-2000:]}


def _gh_headers() -> dict:
    token = config.github_token()
    if not token:
        raise PermissionError("GITHUB_TOKEN is required for GitHub API writes")
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


def _default_branch(slug: str) -> str:
    resp = httpx.get(f"{GITHUB_API}/repos/{slug}", headers=_gh_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json().get("default_branch") or "main"


def _create_pr(slug: str, payload: dict) -> dict:
    resp = httpx.post(
        f"{GITHUB_API}/repos/{slug}/pulls", headers=_gh_headers(), json=payload, timeout=30
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _open_pr(ctx: ProjectContext, args: dict, db: Session | None = None) -> dict:
    _require_approval(db, ctx, "gh_open_pr")
    repo = args.get("repo")
    slug = overview.repo_slug(ctx.repo_url_for(repo))
    if not slug:
        raise ValueError("this repository is not a GitHub repository")
    title = (args.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    head = _git(ctx, ["rev-parse", "--abbrev-ref", "HEAD"], repo=repo)
    base = (args.get("base") or "").strip() or _default_branch(slug)
    pr = _create_pr(
        slug,
        {"title": title, "body": args.get("body") or "", "head": head, "base": base},
    )
    return {
        "number": pr.get("number"),
        "url": pr.get("html_url"),
        "repo": ctx.repo(repo).alias,
        "head": head,
        "base": base,
    }


def _merge_pr(ctx: ProjectContext, args: dict, db: Session | None = None) -> dict:
    _require_approval(db, ctx, "gh_merge_pr")
    repo = args.get("repo")
    slug = overview.repo_slug(ctx.repo_url_for(repo))
    if not slug:
        raise ValueError("this repository is not a GitHub repository")
    number = args.get("number")
    if not number:
        raise ValueError("number is required")
    method = (args.get("method") or "squash").strip().lower()
    if method not in ("squash", "merge", "rebase"):
        raise ValueError("method must be squash, merge, or rebase")
    resp = httpx.put(
        f"{GITHUB_API}/repos/{slug}/pulls/{int(number)}/merge",
        headers=_gh_headers(),
        json={"merge_method": method},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("merged"):
        raise RuntimeError(data.get("message") or "merge failed")
    return {
        "merged": True,
        "number": int(number),
        "repo": ctx.repo(repo).alias,
        "sha": data.get("sha"),
        "message": data.get("message"),
    }


def register(registry: Registry, db: Session | None = None) -> None:
    registry.register(Tool(
        name="write_file",
        description=(
            "Create or overwrite a file in the repository clone (git writes are "
            "enabled for this project). Never writes inside .git."
        ),
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "path": {"type": "string", "description": "path relative to the repo root"},
            "content": {"type": "string", "description": "full file content"},
        }, ["path", "content"]),
        handler=_write_file,
        group="writes",
        effect="write",
    ))
    registry.register(Tool(
        name="git_create_branch",
        description="Create and switch to a new branch in a repository clone.",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "name": {"type": "string"},
        }, ["name"]),
        handler=_create_branch,
        group="writes",
        effect="write",
        delegable=False,
    ))
    registry.register(Tool(
        name="git_commit",
        description="Stage changes (all, or the given paths) and commit them.",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "message": {"type": "string"},
            "paths": {"type": "array", "items": {"type": "string"}},
        }, ["message"]),
        handler=_commit,
        group="writes",
        effect="write",
        delegable=False,
    ))
    registry.register(Tool(
        name="git_push",
        description="Push a branch to origin (uses GITHUB_TOKEN for GitHub remotes).",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "branch": {"type": "string"},
        }, []),
        handler=lambda ctx, a: _push(ctx, a, db),
        group="writes",
        effect="write",
        delegable=False,
    ))
    registry.register(Tool(
        name="gh_merge_pr",
        description=(
            "Merge a pull request (squash by default; method: squash, merge, or "
            "rebase). Requires your approval when the project gates writes."
        ),
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "number": {"type": "integer", "description": "pull request number"},
            "method": {"type": "string", "enum": ["squash", "merge", "rebase"]},
        }, ["number"]),
        handler=lambda ctx, a: _merge_pr(ctx, a, db),
        group="writes",
        effect="write",
        delegable=False,
    ))
    registry.register(Tool(
        name="gh_open_pr",
        description="Open a pull request on GitHub from the current branch.",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "base": {"type": "string", "description": "base branch (default: repo default)"},
        }, ["title"]),
        handler=lambda ctx, a: _open_pr(ctx, a, db),
        group="writes",
        effect="write",
        delegable=False,
    ))
