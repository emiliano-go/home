"""Runtime configuration via environment variables."""

import os
from pathlib import Path


def data_dir() -> Path:
    """Root data directory: registry DB, project clones, totem DBs."""
    return Path(os.environ.get("DATA_DIR", "./data")).resolve()


def github_token() -> str | None:
    """GITHUB_TOKEN env wins; otherwise the token stored from the UI."""
    env = os.environ.get("GITHUB_TOKEN") or None
    if env:
        return env
    from hestia import github_auth

    return github_auth.load_token()


def slug(name: str) -> str:
    """Filesystem-safe directory name for a project."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)


def workspace_dir(name: str) -> Path:
    """Per-project workspace for agent-generated files (plans, specs, notes).

    Lives in the data volume next to the clones, so it persists across
    container restarts and is never inside the repository itself.
    """
    path = data_dir() / "workspaces" / slug(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def port() -> int:
    return int(os.environ.get("PORT", "8080"))


def browser_enabled() -> bool:
    """Env kill switch for the browser tools; the settings toggle is checked too."""
    return os.environ.get("HESTIA_BROWSER", "1").strip().lower() not in ("0", "false", "no", "off")


def browser_headless() -> bool:
    """Headless unless explicitly headed (local debugging)."""
    return os.environ.get("HESTIA_BROWSER_HEADED", "").strip().lower() not in ("1", "true", "yes", "on")


def browser_cdp_url() -> str | None:
    """Connect to an existing Chrome (remote debugging) instead of launching one."""
    return os.environ.get("HESTIA_BROWSER_CDP_URL") or None


def browser_executable() -> str | None:
    """Use a system Chrome/Chromium binary instead of the bundled one."""
    return os.environ.get("HESTIA_BROWSER_EXECUTABLE") or None


def user_memory_path() -> Path:
    """Global Totem user memory DB, kept in the data volume for persistence."""
    return data_dir() / "totem-user.db"


def browser_dir() -> Path:
    """Persistent browser data: profiles, downloads, saved screenshots live here."""
    path = data_dir() / "browser"
    path.mkdir(parents=True, exist_ok=True)
    return path
