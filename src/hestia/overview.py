"""Aggregated per-project insight for the status board and activity timeline.

Everything here is read-only. Local data (git, workspace files, Totem memory)
always works; GitHub data degrades gracefully to ``available: false`` for
non-GitHub remotes, missing tokens, or network errors.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlmodel import Session, select

from hestia import config, repos, totem_store, urls
from hestia.registry.models import Session as ChatSession

GITHUB_API = "https://api.github.com"
_GH_TIMEOUT = 6.0


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


def _parse_dt(value) -> datetime | None:
    """Parse an ISO string, datetime, or epoch-seconds float into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        num = float(text)
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Totem may store "YYYY-MM-DD HH:MM:SS+00:00" style too; best effort.
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(cwd: Path, args: list[str], timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _parse_commit(out: str | None) -> dict | None:
    if not out:
        return None
    parts = out.split("\x1f")
    if len(parts) < 5:
        return None
    sha, short, author, date, subject = parts[:5]
    return {"sha": sha, "short": short, "author": author, "date": date, "subject": subject}


def _last_commit(cwd: Path) -> dict | None:
    return _parse_commit(_git(cwd, ["log", "-1", "--format=%H%x1f%h%x1f%an%x1f%cI%x1f%s"]))


def _upstream_ref(cwd: Path) -> str | None:
    """The upstream ref name (e.g. origin/master), or None when there is none."""
    return _git(cwd, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])


def _remote_commit(cwd: Path) -> tuple[str | None, dict | None]:
    """The last-known remote tip (remote-tracking ref; no fetch here)."""
    ref = _upstream_ref(cwd)
    if not ref:
        return None, None
    commit = _parse_commit(
        _git(cwd, ["log", "-1", "--format=%H%x1f%h%x1f%an%x1f%cI%x1f%s", ref])
    )
    return ref, commit


def _ahead_behind(cwd: Path) -> tuple[int, int]:
    # `@{u}...HEAD` with --left-right prints "<behind>\t<ahead>".
    out = _git(cwd, ["rev-list", "--left-right", "--count", "@{u}...HEAD"])
    if not out:
        return 0, 0
    behind, _, ahead = out.partition("\t")
    try:
        return int(ahead), int(behind)
    except ValueError:
        return 0, 0


def commits_since(cwd: Path, since: datetime | None) -> int:
    if since is None:
        return 0
    out = _git(cwd, ["rev-list", "--count", "HEAD", f"--since={since.isoformat()}"])
    try:
        return int(out) if out is not None else 0
    except ValueError:
        return 0


def recent_commits(cwd: Path, limit: int = 20) -> list[dict]:
    out = _git(cwd, ["log", f"-{limit}", "--format=%H%x1f%h%x1f%an%x1f%cI%x1f%s"])
    if not out:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        commits.append(
            {
                "sha": parts[0],
                "short": parts[1],
                "author": parts[2],
                "date": parts[3],
                "subject": parts[4],
                "timestamp": _parse_dt(parts[3]),
            }
        )
    return commits


def git_summary(path: Path) -> dict:
    ahead, behind = _ahead_behind(path)
    ref, remote = _remote_commit(path)
    return {
        "branch": _git(path, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": _git(path, ["rev-parse", "--short", "HEAD"]),
        "last_commit": _last_commit(path),
        "remote": {"ref": ref, "last_commit": remote} if ref else None,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(_git(path, ["status", "--porcelain"])),
    }


def pending_pull(path: Path, do_fetch: bool = False) -> dict | None:
    """Commits available to pull, or None when up to date / no upstream.

    ``do_fetch`` runs ``git fetch`` first (network); otherwise it uses the
    last-known remote refs, which is cheap enough to call per agent turn.
    """
    if do_fetch:
        _git(path, ["fetch", "--quiet"], timeout=60)
    _, behind = _ahead_behind(path)
    if behind <= 0:
        return None
    return {
        "branch": _git(path, ["rev-parse", "--abbrev-ref", "HEAD"]) or "HEAD",
        "behind": behind,
    }


# --------------------------------------------------------------------------
# workspace files
# --------------------------------------------------------------------------

def workspace_files(project) -> list[dict]:
    root = config.workspace_dir(project.name)
    files = []
    for dirpath, _dirs, filenames in os.walk(root):
        for name in sorted(filenames):
            fp = Path(dirpath) / name
            try:
                st = fp.stat()
            except OSError:
                continue
            files.append(
                {
                    "path": str(fp.relative_to(root)),
                    "bytes": st.st_size,
                    "modified": _parse_dt(st.st_mtime),
                }
            )
    return files


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------

def repo_slug(repo_url: str) -> str | None:
    """Extract owner/repo from a real GitHub remote URL, or None."""
    return urls.github_slug(repo_url)


def gh_get(slug: str, path: str, params: dict | None = None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := config.github_token():
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.get(
        f"{GITHUB_API}/repos/{slug}{path}", headers=headers, params=params, timeout=_GH_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def _norm_pr(pr: dict) -> dict:
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": "draft" if pr.get("draft") else pr.get("state"),
        "draft": bool(pr.get("draft")),
        "user": (pr.get("user") or {}).get("login"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "url": pr.get("html_url"),
        "branch": ((pr.get("head") or {}).get("ref")),
    }


def _norm_issue(issue: dict) -> dict:
    labels = [label.get("name") for label in issue.get("labels", []) if isinstance(label, dict)]
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "user": (issue.get("user") or {}).get("login"),
        "labels": [l for l in labels if l],
        "comments": issue.get("comments"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "url": issue.get("html_url"),
    }


def _norm_run(run: dict) -> dict:
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "branch": run.get("head_branch"),
        "event": run.get("event"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "url": run.get("html_url"),
    }


def github_summary(project, since: datetime | None) -> dict:
    """Counts + latest CI run for a project's primary repo. Never raises."""
    return github_summary_for_url(project.repo_url, since)


def github_summary_for_url(repo_url: str, since: datetime | None) -> dict:
    """Counts + latest CI run for one repository URL. Never raises."""
    slug = repo_slug(repo_url)
    if not slug:
        return {"available": False, "repo": None, "reason": "not a GitHub repository"}
    try:
        prs = [_norm_pr(x) for x in gh_get(slug, "/pulls", {"state": "open", "per_page": 50})]
        issues = [
            _norm_issue(x)
            for x in gh_get(slug, "/issues", {"state": "open", "per_page": 50})
            if "pull_request" not in x
        ]
        runs = [
            _norm_run(x)
            for x in gh_get(slug, "/actions/runs", {"per_page": 20}).get("workflow_runs", [])
        ]
    except Exception as e:  # network, auth, rate limit, or bad repo
        return {"available": False, "repo": slug, "reason": str(e)[:200]}

    failing = [r for r in runs if r.get("conclusion") == "failure"]
    changes = {"prs": 0, "issues": 0, "failed_runs": 0}
    if since is not None:
        for pr in prs:
            if (_parse_dt(pr["updated_at"]) or _now()) >= since:
                changes["prs"] += 1
        for issue in issues:
            if (_parse_dt(issue["updated_at"]) or _now()) >= since:
                changes["issues"] += 1
        changes["failed_runs"] = sum(
            1
            for r in failing
            if (_parse_dt(r["updated_at"]) or _now()) >= since
        )
    return {
        "available": True,
        "repo": slug,
        "open_prs": len(prs),
        "open_issues": len(issues),
        "latest_run": runs[0] if runs else None,
        "failing_runs": len(failing),
        "changes": changes,
    }


def github_item(project, kind: str, number: int) -> dict:
    """Fetch one issue or PR from the primary repo. Raises on failure."""
    return github_item_for_url(project.repo_url, kind, number)


def github_item_for_url(repo_url: str, kind: str, number: int) -> dict:
    """Fetch one issue or PR. Raises on failure (caller maps to an HTTP error)."""
    slug = repo_slug(repo_url)
    if not slug:
        raise ValueError("project repo_url is not a GitHub URL")
    if kind == "prs":
        raw = gh_get(slug, f"/pulls/{number}")
        return {
            "kind": "pr",
            "number": raw.get("number"),
            "title": raw.get("title"),
            "body": raw.get("body") or "",
            "state": raw.get("state"),
            "user": (raw.get("user") or {}).get("login"),
            "url": raw.get("html_url"),
            "branch": (raw.get("head") or {}).get("ref"),
        }
    raw = gh_get(slug, f"/issues/{number}")
    labels = [l.get("name") for l in raw.get("labels", []) if isinstance(l, dict)]
    return {
        "kind": "issue",
        "number": raw.get("number"),
        "title": raw.get("title"),
        "body": raw.get("body") or "",
        "state": raw.get("state"),
        "user": (raw.get("user") or {}).get("login"),
        "url": raw.get("html_url"),
        "labels": [l for l in labels if l],
    }


def github_list(project, kind: str, state: str = "open", limit: int = 30) -> dict:
    """List PRs/issues/runs for the primary repo."""
    return github_list_for_url(project.repo_url, kind, state=state, limit=limit)


def github_list_for_url(repo_url: str, kind: str, state: str = "open", limit: int = 30) -> dict:
    slug = repo_slug(repo_url)
    if not slug:
        return {"available": False, "repo": None, "items": [], "error": "not a GitHub repository"}
    try:
        if kind == "prs":
            data = gh_get(slug, "/pulls", {"state": state, "per_page": limit})
            items = [_norm_pr(x) for x in data]
        elif kind == "issues":
            data = gh_get(slug, "/issues", {"state": state, "per_page": limit})
            items = [_norm_issue(x) for x in data if "pull_request" not in x]
        elif kind == "runs":
            data = gh_get(slug, "/actions/runs", {"per_page": limit}).get("workflow_runs", [])
            items = [_norm_run(x) for x in data]
        else:
            return {"available": False, "repo": slug, "items": [], "error": "unknown kind"}
    except Exception as e:
        return {"available": False, "repo": slug, "items": [], "error": str(e)[:200]}
    return {"available": True, "repo": slug, "items": items}


# --------------------------------------------------------------------------
# changes since last visit
# --------------------------------------------------------------------------

def since_changes(
    project,
    since: datetime | None,
    github: dict | None = None,
    repo_paths: list[Path] | None = None,
) -> dict:
    paths = repo_paths if repo_paths is not None else (
        [Path(project.local_path)] if project.local_path else []
    )
    first_visit = since is None
    memories = [
        m
        for m in totem_store.list_all(repos.memory_root(project), limit=200)
        if since is not None
        and (_parse_dt(m.get("updatedAt") or m.get("updated_at")) or _now()) >= since
    ]
    files = [
        f
        for f in workspace_files(project)
        if since is not None and (f["modified"] or _now()) >= since
    ]
    gh_changes = (github or {}).get("changes", {}) if github and github.get("available") else {}
    counts = {
        "commits": sum(commits_since(p, since) for p in paths),
        "memories": len(memories),
        "files": len(files),
        "prs": gh_changes.get("prs", 0),
        "issues": gh_changes.get("issues", 0),
        "failed_runs": gh_changes.get("failed_runs", 0),
    }
    return {
        "first_visit": first_visit,
        "total": sum(counts.values()),
        "counts": counts,
        "memories": [
            {
                "id": m.get("id"),
                "title": m.get("title"),
                "type": m.get("type"),
                "timestamp": _iso(m.get("updatedAt") or m.get("updated_at")),
            }
            for m in memories[:5]
        ],
        "files": [
            {"path": f["path"], "bytes": f["bytes"], "timestamp": _iso(f["modified"])}
            for f in files[:5]
        ],
    }


# --------------------------------------------------------------------------
# activity timeline
# --------------------------------------------------------------------------

def _mem_timestamp(m: dict):
    return _parse_dt(m.get("updatedAt") or m.get("updated_at") or m.get("createdAt") or m.get("created_at"))


def project_activity(
    project,
    db: Session,
    limit: int = 80,
    include_github: bool = True,
) -> list[dict]:
    repo_rows = repos.repos_for(db, project.id)
    entries: list[dict] = []

    for c in db.exec(
        select(ChatSession)
        .where(ChatSession.project_id == project.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(20)
    ).all():
        entries.append(
            {
                "kind": "session",
                "title": c.title or "Untitled",
                "subtitle": "Conversation",
                "timestamp": _iso(c.updated_at),
                "session_id": c.id,
            }
        )

    for m in totem_store.list_all(repos.memory_root(project), limit=100):
        entries.append(
            {
                "kind": "memory",
                "title": m.get("title"),
                "subtitle": m.get("type"),
                "timestamp": _iso(_mem_timestamp(m)),
                "memory_id": m.get("id"),
            }
        )

    for f in workspace_files(project):
        entries.append(
            {
                "kind": "file",
                "title": f["path"],
                "subtitle": "Generated file",
                "timestamp": _iso(f["modified"]),
                "path": f["path"],
                "bytes": f["bytes"],
            }
        )

    multi = len(repo_rows) > 1
    for row in repo_rows:
        suffix = f" · {row.alias}" if multi else ""
        for c in recent_commits(Path(row.local_path), limit=15):
            entries.append(
                {
                    "kind": "commit",
                    "title": c["subject"],
                    "subtitle": f"{c['short']} by {c['author']}{suffix}",
                    "timestamp": _iso(c["timestamp"]),
                    "sha": c["sha"],
                }
            )

    if include_github:
        for row in repo_rows:
            if not repo_slug(row.repo_url):
                continue
            suffix = f" · {row.alias}" if multi else ""
            try:
                for pr in github_list_for_url(row.repo_url, "prs", state="all", limit=15).get("items", []):
                    entries.append(
                        {
                            "kind": "pr",
                            "title": f"#{pr['number']} {pr['title']}",
                            "subtitle": f"Pull request · {pr.get('state')}{suffix}",
                            "timestamp": _iso(pr.get("updated_at")),
                            "url": pr.get("url"),
                        }
                    )
                for issue in github_list_for_url(row.repo_url, "issues", state="all", limit=15).get("items", []):
                    entries.append(
                        {
                            "kind": "issue",
                            "title": f"#{issue['number']} {issue['title']}",
                            "subtitle": f"Issue · {issue.get('state')}{suffix}",
                            "timestamp": _iso(issue.get("updated_at")),
                            "url": issue.get("url"),
                        }
                    )
                for run in github_list_for_url(row.repo_url, "runs", limit=10).get("items", []):
                    entries.append(
                        {
                            "kind": "run",
                            "title": run.get("name") or "CI run",
                            "subtitle": f"CI · {run.get('conclusion') or run.get('status')}{suffix}",
                            "timestamp": _iso(run.get("updated_at")),
                            "url": run.get("url"),
                        }
                    )
            except Exception:
                pass

    entries = [e for e in entries if e.get("timestamp")]
    entries.sort(key=lambda e: _parse_dt(e["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return entries[:limit]
