"""Read-only git repository tools.

All commands run with cwd inside a project repository (the primary by default,
or the one named by the optional ``repo`` alias). Mutating git subcommands are
rejected by a whitelist before the process spawns.
"""

import subprocess

from hestia import repos as repo_helpers
from hestia.registry.models import Project
from hestia.tools.registry import ProjectContext, Registry, Tool, schema

_ALLOWED = {
    "status": [],
    "log": [],
    "diff": [],
    "show": [],
    "branch": ["--list", "-a", "-r", "--show-current", "-v"],
    "tag": ["--list"],
    "remote": ["-v"],
    "rev-parse": ["--show-toplevel", "--abbrev-ref", "HEAD", "HEAD"],
    "ls-files": [],
    "fetch": ["--all", "--tags", "--prune"],
    "pull": ["--ff-only"],
    "clone": [],
}

_MUTATING_WORDS = {
    "push", "commit", "merge", "rebase", "reset", "clean", "checkout",
    "switch", "restore", "cherry-pick", "revert", "stash", "apply",
    "am", "bisect", "worktree", "submodule", "gc", "prune", "rm", "mv",
    "init", "config", "notes", "reflog", "update-index", "read-tree",
    "write-tree", "commit-tree", "hash-object", "update-ref", "symbolic-ref",
}


def _git(ctx: ProjectContext, args: list[str], repo: str | None = None) -> str:
    if not args:
        raise ValueError("empty git command")
    sub = args[0]
    if sub in _MUTATING_WORDS or sub not in _ALLOWED:
        raise PermissionError(f"git '{sub}' is not allowed (read-only)")
    for arg in args[1:]:
        if arg == "-c" or arg.startswith("-c ") or arg.startswith("--upload-pack") or arg.startswith("--config"):
            raise PermissionError("flag injection not allowed")
    result = subprocess.run(
        ["git", *args],
        cwd=ctx.repo_path(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def _repo_path(ctx: ProjectContext, repo: str | None) -> str:
    return str(ctx.repo_path(repo))


def _repo_list(ctx: ProjectContext) -> list[dict]:
    return [
        {"alias": r.alias, "url": r.repo_url, "path": str(r.local_path), "primary": r.is_primary}
        for r in ctx.repos
    ]


def _repo_add(ctx: ProjectContext, args: dict, db) -> dict:
    url = (args.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    project = db.get(Project, ctx.project_id)
    if project is None:
        raise ValueError("project not found")
    alias = (args.get("alias") or "").strip().lower()
    if not alias:
        taken = {r.alias for r in repo_helpers.repos_for(db, project.id)}
        alias = repo_helpers.default_alias(url, taken)
    repo = repo_helpers.add_repo(db, project, alias, url)
    return {
        "alias": repo.alias,
        "url": repo.repo_url,
        "path": repo.local_path,
        "primary": repo.is_primary,
    }


def register(registry: Registry, db=None) -> None:
    registry.register(Tool(
        name="git_pull",
        description="Fast-forward pull a repository (primary by default) from its remote.",
        parameters=schema({"repo": {"type": "string", "description": "repo alias"}}, []),
        handler=lambda ctx, a: _git(ctx, ["pull", "--ff-only"], a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="git_log",
        description="Show recent commit history (git log).",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "max_count": {"type": "integer", "description": "number of commits"},
            "oneline": {"type": "boolean"},
            "path": {"type": "string", "description": "optional path filter"},
        }, []),
        handler=lambda ctx, a: _git(ctx, ["log", f"--max-count={a.get('max_count', 20)}"]
                                    + (["--oneline"] if a.get("oneline") else [])
                                    + (["--", a["path"]] if a.get("path") else []),
                                    a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="git_diff",
        description="Show working-tree or between-commit diffs (git diff).",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "ref": {"type": "string", "description": "e.g. HEAD~1 or a commit range a..b"},
            "path": {"type": "string"},
        }, []),
        handler=lambda ctx, a: _git(ctx, ["diff"]
                                    + ([a["ref"]] if a.get("ref") else [])
                                    + (["--", a["path"]] if a.get("path") else []),
                                    a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="git_show",
        description="Show a commit (git show <ref>).",
        parameters=schema({
            "repo": {"type": "string", "description": "repo alias"},
            "ref": {"type": "string"},
        }, ["ref"]),
        handler=lambda ctx, a: _git(ctx, ["show", a["ref"]], a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="git_status",
        description="Working tree status (git status).",
        parameters=schema({"repo": {"type": "string", "description": "repo alias"}}, []),
        handler=lambda ctx, a: _git(ctx, ["status"], a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="git_branches",
        description="List local and remote branches.",
        parameters=schema({"repo": {"type": "string", "description": "repo alias"}}, []),
        handler=lambda ctx, a: _git(ctx, ["branch", "-a", "-v"], a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="repo_path",
        description="Absolute path of a project repository on this server.",
        parameters=schema({"repo": {"type": "string", "description": "repo alias"}}, []),
        handler=lambda ctx, a: _repo_path(ctx, a.get("repo")),
        group="repo",
    ))
    registry.register(Tool(
        name="repo_list",
        description="List the project's repositories (alias, URL, path, primary).",
        parameters=schema({}, []),
        handler=lambda ctx, a: _repo_list(ctx),
        group="repo",
    ))
    if db is not None:
        registry.register(Tool(
            name="repo_add",
            description=(
                "Clone a Git repository into this project and register it under an "
                "alias. Use when the project has no repositories or needs another "
                "one; cloning can take a while."
            ),
            parameters=schema({
                "url": {"type": "string", "description": "Git clone URL"},
                "alias": {"type": "string", "description": "short name (default: repo name)"},
            }, ["url"]),
            handler=lambda ctx, a: _repo_add(ctx, a, db),
            group="repo",
            effect="write",
            delegable=False,
        ))
