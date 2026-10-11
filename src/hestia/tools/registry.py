"""Tool registry: MCP-style tools shared by the built-in agent and the MCP server.

Every tool takes a ProjectContext plus a JSON-args dict and returns a
JSON-serializable result. All tools are read-only with respect to project code.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class RepoRef:
    """One repository of a project, as seen by tools and the prompt."""

    alias: str
    repo_url: str
    local_path: Path
    is_primary: bool = False


@dataclass
class ProjectContext:
    project_id: int
    name: str
    repo_url: str  # primary repo mirror ("" when repo-less)
    local_path: Path  # primary clone path (workspace when repo-less)
    workspace_path: Path | None = None
    session_id: str | None = None  # set for interactive chat turns
    run_id: str | None = None  # RunManager run backing this execution
    tool_call_id: str | None = None  # current tool call (set by the agent loop)
    allow_git_writes: bool = False  # project opt-in; gates write-mode clone edits
    write_mode: str = "read"  # read | ask | auto | yolo; refines allow_git_writes
    require_plan: bool = False  # project opt-in; writes need a plan + step checks
    plan_check_pending: bool = False  # runtime: a gated write awaits its drift check
    write_allowlist: tuple[str, ...] | None = None  # subagent write scope (globs)
    allow_local_browser: bool = False  # project opt-in; allows localhost browsing
    memory_override: Path | None = None  # keep Totem on the real clone during a sandbox turn
    repos: list[RepoRef] = field(default_factory=list)

    @property
    def has_repos(self) -> bool:
        return bool(self.repos)

    @property
    def memory_path(self) -> Path:
        """Totem lives in the primary clone, or the workspace when repo-less."""
        if self.memory_override is not None:
            return self.memory_override
        primary = self.primary_repo()
        if primary is not None:
            return primary.local_path
        return self.workspace_path or self.local_path

    def primary_repo(self) -> RepoRef | None:
        for repo in self.repos:
            if repo.is_primary:
                return repo
        if self.repos:
            return self.repos[0]
        # Contexts constructed directly (tests, MCP, one-off callers) carry a
        # path but no repo rows: treat it as an implicit primary repository.
        # A repo-less project from from_project has local_path == workspace.
        if self.local_path and self.local_path != self.workspace_path:
            return RepoRef(
                alias="main",
                repo_url=self.repo_url,
                local_path=self.local_path,
                is_primary=True,
            )
        return None

    def repo(self, alias: str | None = None) -> RepoRef:
        """Resolve an alias (or the primary) to a repo; raise with guidance."""
        if not self.repos:
            implicit = self.primary_repo()
            if implicit is None:
                raise ValueError(
                    "this project has no repositories; add one with repo_add "
                    "or from the project's Repositories page"
                )
            if alias and alias != implicit.alias:
                raise ValueError(
                    f"unknown repo '{alias}'; available repos: {implicit.alias}"
                )
            return implicit
        if alias:
            for repo in self.repos:
                if repo.alias == alias:
                    return repo
            available = ", ".join(r.alias for r in self.repos)
            raise ValueError(f"unknown repo '{alias}'; available repos: {available}")
        primary = self.primary_repo()
        assert primary is not None
        return primary

    def repo_path(self, alias: str | None = None) -> Path:
        return self.repo(alias).local_path

    def repo_url_for(self, alias: str | None = None) -> str:
        return self.repo(alias).repo_url

    @classmethod
    def from_project(cls, project) -> "ProjectContext":
        from hestia import config

        workspace = config.workspace_dir(project.name)
        refs: list[RepoRef] = []
        try:
            from sqlmodel import Session, select

            from hestia.registry.db import engine
            from hestia.registry.models import ProjectRepo

            with Session(engine()) as db:
                rows = db.exec(
                    select(ProjectRepo)
                    .where(ProjectRepo.project_id == project.id)
                    .order_by(ProjectRepo.id)
                ).all()
            rows = sorted(rows, key=lambda r: (not r.is_primary, r.id or 0))
            refs = [
                RepoRef(
                    alias=r.alias,
                    repo_url=r.repo_url,
                    local_path=Path(r.local_path),
                    is_primary=r.is_primary,
                )
                for r in rows
            ]
        except Exception:
            refs = []  # pre-migration DB or no registry yet
        if not refs and getattr(project, "repo_url", ""):
            refs = [
                RepoRef(
                    alias="main",
                    repo_url=project.repo_url,
                    local_path=Path(project.local_path),
                    is_primary=True,
                )
            ]
        primary = next((r for r in refs if r.is_primary), refs[0] if refs else None)
        mode = (getattr(project, "write_mode", "") or "").strip().lower()
        if mode not in ("read", "ask", "auto", "yolo"):
            mode = "auto" if getattr(project, "allow_git_writes", False) else "read"
        return cls(
            project_id=project.id,
            name=project.name,
            repo_url=primary.repo_url if primary else "",
            local_path=primary.local_path if primary else workspace,
            workspace_path=workspace,
            allow_git_writes=bool(getattr(project, "allow_git_writes", False)),
            write_mode=mode,
            require_plan=bool(getattr(project, "require_plan", False)),
            allow_local_browser=bool(getattr(project, "allow_local_browser", False)),
            repos=refs,
        )


def write_allowed(ctx: ProjectContext, rel: str) -> bool:
    """Whether a write to ``rel`` is inside the context's write scope.

    No scope set means unrestricted. Otherwise globs match POSIX-style relative
    paths against the repo root or workspace root.
    """
    if not ctx.write_allowlist:
        return True
    from pathlib import PurePosixPath

    rel = rel.replace("\\", "/").lstrip("./")
    return any(PurePosixPath(rel).full_match(p) for p in ctx.write_allowlist)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the tool arguments
    handler: Callable[[ProjectContext, dict[str, Any]], Any]
    group: str = ""  # repo | files | github | memory | agents
    effect: str = "read"  # read | write; write tools are dropped in read delegation mode
    delegable: bool = True  # False: principal-only, never handed to a subagent


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def filtered(self, groups: list[str]) -> "Registry":
        """A view restricted to the given tool groups (plus groupless tools)."""
        view = Registry()
        for tool in self._tools.values():
            if not tool.group or tool.group in groups:
                view.register(tool)
        return view

    def readonly(self) -> "Registry":
        """A view without write-effect tools (read delegation mode, side questions)."""
        view = Registry()
        for tool in self._tools.values():
            if tool.effect == "read":
                view.register(tool)
        return view

    def delegable(self) -> "Registry":
        """A view without principal-only tools (what a subagent may ever use)."""
        view = Registry()
        for tool in self._tools.values():
            if tool.delegable:
                view.register(tool)
        return view

    def openai_schemas(self, tools: list["Tool"] | None = None) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": t.parameters.get("properties", {}),
                        "required": t.parameters.get("required", []),
                    },
                },
            }
            for t in (tools if tools is not None else self.all())
        ]


def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}
