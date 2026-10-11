"""Project CRUD + multi-repo clone + repo status."""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from sqlmodel import Session, select

from hestia import config, overview, repos, sandbox, snapshots, totem_store
from hestia.registry.db import session
from hestia.registry.models import (
    Goal,
    InboxItem,
    Message,
    Milestone,
    Project,
    ProjectRepo,
    Reminder,
    Schedule,
    Task,
    TaskComment,
    Usage,
    Watch,
)
from hestia.registry.models import Session as ChatSession

router = APIRouter(prefix="/api/projects", tags=["projects"])

_PROGRESS_RE = re.compile(r"(Receiving objects|Resolving deltas):\s+(\d+)%")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _git_out(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else ""


def _clone_output(repo_url: str, dest: Path):
    """Run `git clone --progress`, yielding each output line as it arrives."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["git", *repos.auth_args(repo_url), "clone", "--progress", "--", repo_url, str(dest)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    buf = ""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":
            line = buf.strip()
            buf = ""
            if line:
                lines.append(line)
                yield line
        else:
            buf += ch
    proc.wait()
    yield {"exit": proc.returncode, "lines": lines}


def _normalize_repos(body: dict) -> list[dict]:
    """Validate/normalize the wizard's repo list; supports the legacy repo_url."""
    raw = body.get("repos")
    if not raw and (body.get("repo_url") or "").strip():
        raw = [{"url": body["repo_url"], "alias": "main", "primary": True}]
    if not raw:
        return []
    specs: list[dict] = []
    taken: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(400, "each repo must be an object with url and alias")
        url = (item.get("url") or "").strip()
        if not url:
            raise HTTPException(400, "each repo needs a url")
        alias = (item.get("alias") or "").strip().lower() or repos.default_alias(url, taken)
        if not repos.valid_alias(alias):
            raise HTTPException(
                400, f"invalid alias '{alias}': 1-32 chars, lowercase letters, digits, - or _"
            )
        if alias in taken:
            raise HTTPException(400, f"duplicate repo alias: {alias}")
        taken.add(alias)
        specs.append({"url": url, "alias": alias, "primary": bool(item.get("primary"))})
    marked = [s for s in specs if s["primary"]]
    for spec in specs:
        spec["primary"] = False
    (marked[0] if marked else specs[0])["primary"] = True
    return specs


def _repo_status(path: str) -> dict:
    p = Path(path)
    return {
        "head": _git_out(["rev-parse", "--short", "HEAD"], p),
        "branch": _git_out(["rev-parse", "--abbrev-ref", "HEAD"], p),
        "behind": "",
    }


def _repo_entry(row: ProjectRepo) -> dict:
    return {
        "id": row.id,
        "alias": row.alias,
        "repo_url": row.repo_url,
        "local_path": row.local_path,
        "is_primary": row.is_primary,
        "status": _repo_status(row.local_path),
    }


def _apply_options(project: Project, body: dict) -> None:
    if "description" in body:
        project.description = (body.get("description") or "").strip()
    if body.get("provider_id"):
        project.default_provider_id = int(body["provider_id"])
    if "allow_git_writes" in body:
        project.allow_git_writes = bool(body["allow_git_writes"])
    if "write_mode" in body:
        mode = str(body.get("write_mode") or "").strip().lower()
        if mode in ("", "read", "ask", "auto", "yolo"):
            project.write_mode = mode
    if "allow_local_browser" in body:
        project.allow_local_browser = bool(body["allow_local_browser"])


def _create_project_events(name: str, body: dict, s: Session):
    """Yield SSE events for each real step of creating a project."""
    specs = _normalize_repos(body)
    root = config.data_dir() / "repos" / config.slug(name)
    if root.exists():
        yield _sse({"event": "error", "detail": f"clone directory already exists: {root}"})
        return
    multi = len(specs) > 1

    for spec in specs:
        step = f"clone:{spec['alias']}" if multi else "clone"
        label = f"Cloning {spec['alias']}" if multi else "Cloning repository"
        yield _sse({"event": "step", "step": step, "label": label, "status": "running"})
        dest = repos.clone_dir(name, spec["alias"])
        returncode = None
        lines: list[str] = []
        for item in _clone_output(spec["url"], dest):
            if isinstance(item, dict):
                returncode, lines = item["exit"], item["lines"]
                continue
            m = _PROGRESS_RE.search(item)
            if m:
                yield _sse(
                    {"event": "progress", "step": step, "percent": int(m.group(2)), "detail": item}
                )
        if returncode != 0:
            shutil.rmtree(root, ignore_errors=True)
            detail = "\n".join(lines[-8:]) or f"git clone exited {returncode}"
            yield _sse({"event": "error", "detail": f"git clone failed: {detail[:500]}"})
            return
        yield _sse({"event": "step", "step": step, "status": "done"})

    yield _sse(
        {"event": "step", "step": "agents", "label": "Reading AGENTS.md", "status": "running"}
    )
    primary = next((spec for spec in specs if spec["primary"]), specs[0] if specs else None)
    agents_md = None
    if primary is not None:
        agents = repos.clone_dir(name, primary["alias"]) / "AGENTS.md"
        agents_md = agents.read_text()[:20_000] if agents.exists() else None
    yield _sse({"event": "step", "step": "agents", "status": "done"})

    yield _sse(
        {
            "event": "step",
            "step": "memory",
            "label": "Initializing project memory",
            "status": "running",
        }
    )
    project = Project(name=name, agents_md=agents_md)
    _apply_options(project, body)
    s.add(project)
    s.commit()
    s.refresh(project)
    for spec in specs:
        s.add(
            ProjectRepo(
                project_id=project.id,
                alias=spec["alias"],
                repo_url=spec["url"],
                local_path=str(repos.clone_dir(name, spec["alias"])),
                is_primary=spec["primary"],
            )
        )
    s.commit()
    repos.sync_legacy(s, project)
    s.commit()
    s.refresh(project)
    totem_store.recent(repos.memory_root(project))  # opens + inits the Totem DB
    yield _sse({"event": "step", "step": "memory", "status": "done"})
    yield _sse({"event": "done", "project": project.model_dump(mode="json")})


@router.post("/stream")
def create_project_stream(body: dict, s: Session = Depends(session)):
    """Create a project while streaming clone/init progress as SSE."""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    _normalize_repos(body)  # validate before the stream starts
    return StreamingResponse(
        _create_project_events(name, body, s), media_type="text/event-stream"
    )


@router.get("")
def list_projects(s: Session = Depends(session)):
    return s.exec(select(Project)).all()


@router.post("", status_code=201)
def create_project(body: dict, s: Session = Depends(session)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    specs = _normalize_repos(body)
    root = config.data_dir() / "repos" / config.slug(name)
    if root.exists():
        raise HTTPException(409, f"clone directory already exists: {root}")
    cloned: list[dict] = []
    try:
        for spec in specs:
            dest = repos.clone_dir(name, spec["alias"])
            repos.clone(spec["url"], dest)
            cloned.append(spec)
    except RuntimeError as e:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"git clone failed: {e}")

    primary = next((spec for spec in specs if spec["primary"]), specs[0] if specs else None)
    agents_md = None
    if primary is not None:
        agents = repos.clone_dir(name, primary["alias"]) / "AGENTS.md"
        agents_md = agents.read_text()[:20_000] if agents.exists() else None
    project = Project(name=name, agents_md=agents_md)
    _apply_options(project, body)
    s.add(project)
    s.commit()
    s.refresh(project)
    for spec in specs:
        s.add(
            ProjectRepo(
                project_id=project.id,
                alias=spec["alias"],
                repo_url=spec["url"],
                local_path=str(repos.clone_dir(name, spec["alias"])),
                is_primary=spec["primary"],
            )
        )
    s.commit()
    repos.sync_legacy(s, project)
    s.commit()
    s.refresh(project)
    totem_store.recent(repos.memory_root(project))
    return project


@router.get("/{project_id}")
def get_project(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    rows = repos.repos_for(s, project.id)
    entries = [_repo_entry(r) for r in rows]
    head = next((e for e in entries if e["is_primary"]), entries[0] if entries else None)
    status = head["status"] if head else {"head": "", "branch": "", "behind": ""}
    return {**project.model_dump(), "status": status, "repos": entries}


@router.get("/{project_id}/repos")
def list_repos(project_id: int, github: bool = False, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    entries = [_repo_entry(r) for r in repos.repos_for(s, project.id)]
    if github:
        for entry in entries:
            entry["github"] = overview.github_summary_for_url(entry["repo_url"], since=None)
    return entries


@router.post("/{project_id}/repos", status_code=201)
def add_repo(project_id: int, body: dict, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    alias = (body.get("alias") or "").strip().lower()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    if not alias:
        taken = {r.alias for r in repos.repos_for(s, project.id)}
        alias = repos.default_alias(url, taken)
    try:
        row = repos.add_repo(s, project, alias, url)
    except ValueError as e:
        raise HTTPException(409 if "exists" in str(e) else 400, str(e))
    except RuntimeError as e:
        raise HTTPException(400, f"git clone failed: {e}")
    return _repo_entry(row)


@router.delete("/{project_id}/repos/{alias}", status_code=204)
def remove_repo(project_id: int, alias: str, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    try:
        repos.remove_repo(s, project, alias)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/open")
def open_project(project_id: int, s: Session = Depends(session)):
    """Mark a project as recently opened (drives the landing dashboard)."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    previous = project.last_opened_at
    project.last_opened_at = datetime.now(timezone.utc)
    s.add(project)
    s.commit()
    s.refresh(project)
    return {
        **project.model_dump(),
        "previous_opened_at": previous.isoformat() if previous else None,
    }


@router.put("/{project_id}")
def update_project(project_id: int, body: dict, s: Session = Depends(session)):
    """Update description, budget, and project flags."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if "token_budget" in body:
        value = body["token_budget"]
        try:
            project.token_budget = int(value) if value not in (None, "", 0) else None
        except (TypeError, ValueError):
            raise HTTPException(400, "token_budget must be a number")
    if "budget_enforced" in body:
        project.budget_enforced = bool(body["budget_enforced"])
    if "require_write_approval" in body:
        project.require_write_approval = bool(body["require_write_approval"])
    if "require_plan" in body:
        project.require_plan = bool(body["require_plan"])
    if "write_mode" in body:
        mode = str(body.get("write_mode") or "").strip().lower()
        if mode not in ("", "read", "ask", "auto", "yolo"):
            raise HTTPException(400, "write_mode must be read, ask, auto, or yolo")
        project.write_mode = mode
    if "allow_local_browser" in body:
        project.allow_local_browser = bool(body["allow_local_browser"])
    if "description" in body:
        project.description = (body.get("description") or "").strip()
    s.add(project)
    s.commit()
    s.refresh(project)
    return project


@router.get("/{project_id}/sandbox")
def get_sandbox(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return sandbox.latest(repos.memory_root(project)) or {}


@router.post("/{project_id}/sandbox/promote")
def promote_sandbox(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = repos.memory_root(project)
    info = sandbox.latest(root)
    if not info:
        raise HTTPException(404, "no sandbox to promote")
    rows = repos.repos_for(s, project_id)
    paths = {row.alias: Path(row.local_path) for row in rows} or {"main": root}
    results = {}
    try:
        for alias, text in info.get("patches", {}).items():
            results[alias] = sandbox.promote(paths.get(alias, root), text)
    except RuntimeError as error:
        raise HTTPException(409, f"could not apply sandbox patch: {error}") from error
    sandbox.clear(root)
    return {"promoted": results}


@router.post("/{project_id}/sandbox/discard")
def discard_sandbox(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = repos.memory_root(project)
    info = sandbox.latest(root)
    if info:
        sandbox.discard(info.get("path", ""))
    sandbox.clear(root)
    return {"discarded": True}


@router.get("/{project_id}/snapshots")
def list_snapshots(project_id: int, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return snapshots.recent(repos.memory_root(project), limit=50)


@router.post("/{project_id}/revert")
def revert_snapshot(project_id: int, body: dict | None = None, s: Session = Depends(session)):
    """Restore the project clone to its latest snapshot (or a given sha)."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = repos.memory_root(project)
    sha = (body or {}).get("sha")
    if not sha:
        entries = snapshots.recent(root)
        if not entries:
            raise HTTPException(404, "no snapshots to revert to")
        sha = entries[-1]["sha"]
    try:
        return snapshots.restore(root, sha)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(500, str(error)) from error


@router.put("/{project_id}/git-writes")
def set_git_writes(project_id: int, body: dict, s: Session = Depends(session)):
    """Explicit opt-in for mutating git tools (branch/commit/push/PR)."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    project.allow_git_writes = bool(body.get("enabled"))
    if "write_mode" in body:
        mode = str(body.get("write_mode") or "").strip().lower()
        if mode in ("", "read", "ask", "auto", "yolo"):
            project.write_mode = mode
    s.add(project)
    s.commit()
    s.refresh(project)
    return project


@router.post("/{project_id}/pull")
def pull_project(project_id: int, body: dict | None = None, repo: str | None = None, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    rows = repos.repos_for(s, project.id)
    if repo:
        rows = [r for r in rows if r.alias == repo]
        if not rows:
            raise HTTPException(404, f"unknown repo alias: {repo}")
    if not rows:
        raise HTTPException(400, "project has no repositories")

    results = []
    for row in rows:
        result = subprocess.run(
            ["git", *repos.auth_args(row.repo_url), "pull", "--ff-only"],
            cwd=row.local_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        results.append(
            {
                "alias": row.alias,
                "ok": result.returncode == 0,
                "output": result.stdout.strip() if result.returncode == 0 else "",
                "error": "" if result.returncode == 0 else result.stderr.strip()[:500],
            }
        )
    failed = [r for r in results if not r["ok"]]
    if failed and len(failed) == len(results):
        raise HTTPException(400, failed[0]["error"] or "git pull failed")

    head = next((r for r in rows if r.is_primary), rows[0])
    agents = Path(head.local_path) / "AGENTS.md"
    project.agents_md = agents.read_text()[:20_000] if agents.exists() else None
    s.add(project)
    # the pulls are done: clear "Pull pending" inbox items for this project
    s.exec(delete(InboxItem).where(InboxItem.project_id == project_id, InboxItem.kind == "pull"))
    s.commit()
    output = next((r["output"] for r in results if r["alias"] == head.alias), "")
    return {"output": output, "results": results}


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, s: Session = Depends(session)):
    """Delete a project, every row that belongs to it, and its clones/workspace."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    session_ids = list(
        s.exec(select(ChatSession.id).where(ChatSession.project_id == project_id)).all()
    )
    task_ids = list(
        s.exec(select(Task.id).where(Task.project_id == project_id)).all()
    )
    if session_ids:
        s.exec(delete(Message).where(Message.session_id.in_(session_ids)))
    if task_ids:
        s.exec(delete(TaskComment).where(TaskComment.task_id.in_(task_ids)))
    s.exec(delete(ProjectRepo).where(ProjectRepo.project_id == project_id))
    for model in (
        Task,
        Milestone,
        Goal,
        Schedule,
        Reminder,
        Watch,
        InboxItem,
        Usage,
        ChatSession,
    ):
        s.exec(delete(model).where(model.project_id == project_id))
    s.delete(project)
    s.commit()

    shutil.rmtree(config.data_dir() / "repos" / config.slug(project.name), ignore_errors=True)
    shutil.rmtree(
        config.data_dir() / "workspaces" / config.slug(project.name), ignore_errors=True
    )
