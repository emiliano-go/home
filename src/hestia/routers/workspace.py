"""Workspace file browsing: per project and a cross-project gallery."""

import fnmatch
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlmodel import Session, select

from hestia import config
from hestia.registry.db import session
from hestia.registry.models import Project

router = APIRouter(prefix="/api", tags=["workspace"])

_MAX_BYTES = 200_000


def _list_files(root: Path, pattern: str, limit: int = 500) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in sorted(filenames):
            rel = str((Path(dirpath) / f).relative_to(root))
            if fnmatch.fnmatch(rel, pattern.replace("**/", "*")):
                out.append(rel)
                if len(out) >= limit:
                    return out
    return out


@router.get("/projects/{project_id}/workspace")
def list_workspace(project_id: int, pattern: str = "*", s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = config.workspace_dir(project.name)
    return {
        "root": str(root),
        "files": [
            {"path": rel, "bytes": (root / rel).stat().st_size}
            for rel in _list_files(root, pattern)
        ],
    }


@router.get("/projects/{project_id}/workspace/file", response_class=PlainTextResponse)
def read_workspace_file(project_id: int, path: str, s: Session = Depends(session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = config.workspace_dir(project.name).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root) + os.sep) or not target.is_file():
        raise HTTPException(404, "file not found")
    return target.read_bytes()[:_MAX_BYTES].decode("utf-8", "replace")


@router.get("/projects/{project_id}/workspace/raw")
def raw_workspace_file(project_id: int, path: str, s: Session = Depends(session)):
    """Serve a workspace file verbatim (images render in the browser)."""
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    root = config.workspace_dir(project.name).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root) + os.sep) or not target.is_file():
        raise HTTPException(404, "file not found")
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@router.get("/gallery")
def gallery(s: Session = Depends(session)):
    """All workspace files across projects, for the global gallery view."""
    entries = []
    for project in s.exec(select(Project)).all():
        root = config.workspace_dir(project.name)
        for rel in _list_files(root, "*", limit=200):
            entries.append({
                "project_id": project.id,
                "project": project.name,
                "path": rel,
                "bytes": (root / rel).stat().st_size,
            })
    return entries
