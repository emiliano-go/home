"""Cross-project search: Totem memory, workspace files, and session titles."""

from __future__ import annotations

from sqlmodel import Session, select

from hestia import config, repos, totem_store
from hestia.registry.models import Project, Session as ChatSession
from hestia.routers.workspace import _list_files

_MAX_FILES = 300
_MAX_FILE_BYTES = 200_000
_SNIPPET = 160


def _snippet(text: str, needle: str) -> str | None:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
    start = max(0, idx - _SNIPPET // 2)
    return text[start : start + _SNIPPET].replace("\n", " ").strip()


def global_search(db: Session, query: str, limit: int = 8) -> dict:
    q = (query or "").strip()
    if not q:
        return {"query": "", "memories": [], "files": [], "sessions": []}

    projects = db.exec(select(Project)).all()
    by_id = {p.id: p for p in projects}

    sessions = []
    for c in db.exec(
        select(ChatSession).where(ChatSession.title.contains(q)).limit(limit)
    ).all():
        project = by_id.get(c.project_id)
        sessions.append(
            {
                "id": c.id,
                "title": c.title,
                "project_id": c.project_id,
                "project": project.name if project else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
        )

    memories = []
    for p in projects:
        if len(memories) >= limit:
            break
        try:
            found = totem_store.search(repos.memory_root(p), q, limit=limit)
        except Exception:
            continue
        for m in found:
            memories.append(
                {
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "type": m.get("type"),
                    "statement": (m.get("statement") or "")[:300],
                    "project_id": p.id,
                    "project": p.name,
                }
            )
            if len(memories) >= limit:
                break

    # ponytail: linear scan of workspace text files per query; fine while
    # workspaces hold dozens of generated docs, move to an index if they grow.
    files = []
    scanned = 0
    for p in projects:
        if len(files) >= limit or scanned >= _MAX_FILES:
            break
        root = config.workspace_dir(p.name)
        for rel in _list_files(root, "*", limit=_MAX_FILES):
            if len(files) >= limit or scanned >= _MAX_FILES:
                break
            scanned += 1
            fp = root / rel
            try:
                size = fp.stat().st_size
                if q.lower() in rel.lower():
                    files.append(
                        {"project_id": p.id, "project": p.name, "path": rel, "bytes": size, "snippet": None}
                    )
                    continue
                if size > _MAX_FILE_BYTES:
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            snippet = _snippet(text, q)
            if snippet:
                files.append(
                    {"project_id": p.id, "project": p.name, "path": rel, "bytes": size, "snippet": snippet}
                )

    return {"query": q, "memories": memories, "files": files, "sessions": sessions}
