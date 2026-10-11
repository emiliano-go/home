"""URL trust helpers: exact hostname checks before forwarding credentials.

Substring checks like ``"github.com" in url`` are unsafe: a URL such as
``https://github.com.attacker.example/x`` would receive the GitHub token.
"""

from urllib.parse import urlparse

GITHUB_HOSTS = {"github.com"}


def github_host(url: str) -> bool:
    """True only for https URLs whose hostname is exactly github.com."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in GITHUB_HOSTS


def github_slug(url: str) -> str | None:
    """owner/repo from a real GitHub URL; None for every other host."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in GITHUB_HOSTS:
        return None
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) < 2 or not all(parts[-2:]):
        return None
    return "/".join(parts[-2:])
