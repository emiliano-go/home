"""Installable agent skills: SKILL.md packages from git, npm, archives, or paths.

Skills are global (shared by every project's agent). Each skill is a directory
under ``DATA_DIR/skills/<slug>/`` containing a ``SKILL.md`` with optional YAML
frontmatter (``name``, ``description``). Agents see the name/description in
their system prompt and load the full body with the ``read_skill`` tool.

Supported sources:
- ``owner/repo`` or a github URL (optional ``#subpath``)
- ``npm:<package>``
- any ``.tar.gz`` / ``.tgz`` / ``.zip`` URL
- a local directory path (handy for development)
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from hestia import config, urls


class InvalidSource(ValueError):
    """Raised for unrecognized sources or failed installs."""


_GITHUB_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".tar")
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
_META_FILE = ".hestia-skill.json"


@dataclass
class Skill:
    slug: str
    name: str
    description: str
    source: str
    body: str

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "source": self.source,
        }


def skills_dir() -> Path:
    path = config.data_dir() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_source(source: str) -> tuple[str, str, str | None]:
    """Return (kind, target, subpath). kind is git|npm|archive|path."""
    s = (source or "").strip()
    if not s:
        raise InvalidSource("source is required")
    if s.startswith("npm:"):
        return "npm", s[4:].strip(), None
    if s.startswith(("http://", "https://")):
        if "github.com" in urlparse(s).netloc:
            return "git", s, None
        if s.lower().endswith(_ARCHIVE_SUFFIXES):
            return "archive", s, None
        return "git", s, None
    local = Path(s).expanduser()
    if local.exists():
        return "path", str(local.resolve()), None
    repo, _, frag = s.partition("#")
    if _GITHUB_RE.match(repo):
        return "git", f"https://github.com/{repo}", (frag or None)
    raise InvalidSource(f"unrecognized source: {source}")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML frontmatter: `key: value` lines between --- fences."""
    text = text.lstrip("\ufeff")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip("\n")
            body = text[end + 4 :].lstrip("\n")
            meta: dict[str, str] = {}
            for line in block.splitlines():
                if ":" in line and not line.lstrip().startswith("#"):
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip().strip("'\"")
            return meta, body
    return {}, text


def _first_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return ""


def _safe_extract(data: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = dest.resolve()
            for name in archive.namelist():
                target = (root / name).resolve()
                if root not in target.parents and target != root:
                    raise InvalidSource("unsafe path in archive")
            archive.extractall(dest)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            archive.extractall(dest, filter="data")


def _download(url: str) -> bytes:
    try:
        response = httpx.get(url, timeout=120, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise InvalidSource(f"download failed: {str(e)[:200]}") from e
    return response.content


def _fetch_git(repo: str, subpath: str | None, workdir: Path) -> tuple[Path, str | None]:
    repo, _, frag = repo.partition("#")
    subpath = subpath or frag or None
    cmd = ["git"]
    token = config.github_token()
    if token and urls.github_host(repo):
        cmd += ["-c", f"http.extraheader=Authorization: Bearer {token}"]
    dest = workdir / "src"
    cmd += ["clone", "--depth", "1", "--", repo, str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise InvalidSource(f"git clone failed: {result.stderr.strip()[:300]}")
    return dest, subpath


def _fetch_npm(package: str, workdir: Path) -> tuple[Path, str | None]:
    name = package.strip()
    meta = _download_json(f"https://registry.npmjs.org/{name.replace('/', '%2f')}")
    version = (meta.get("dist-tags") or {}).get("latest")
    tarball = ((meta.get("versions") or {}).get(version) or {}).get("dist", {}).get("tarball")
    if not tarball:
        raise InvalidSource(f"npm package not found: {package}")
    dest = workdir / "src"
    _safe_extract(_download(tarball), dest)
    root = dest / "package"
    return (root if root.exists() else dest), None


def _download_json(url: str) -> dict:
    try:
        response = httpx.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise InvalidSource(f"registry request failed: {str(e)[:200]}") from e


def _find_skill_files(root: Path, subpath: str | None) -> list[Path]:
    base = (root / subpath) if subpath else root
    if not base.exists():
        raise InvalidSource(f"path not found in source: {subpath}")
    found = []
    for path in base.rglob("*"):
        if path.name.lower() != "skill.md":
            continue
        if _SKIP_DIRS.intersection(path.parts):
            continue
        found.append(path)
    return sorted(found)


def _install_one(skill_root: Path, source: str) -> Skill:
    skill_md = next(
        p for p in skill_root.iterdir() if p.name.lower() == "skill.md"
    )
    raw = skill_md.read_text(errors="replace")
    meta, body = parse_frontmatter(raw)
    name = meta.get("name") or skill_root.name
    description = meta.get("description") or _first_line(body)
    slug = config.slug(name) or skill_root.name
    dest = skills_dir() / slug
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        skill_root,
        dest,
        ignore=shutil.ignore_patterns(*_SKIP_DIRS),
        dirs_exist_ok=True,
    )
    (dest / _META_FILE).write_text(
        json.dumps(
            {"slug": slug, "name": name, "description": description, "source": source},
            indent=2,
        )
    )
    return Skill(slug=slug, name=name, description=description, source=source, body=body)


def install(source: str, subpath: str | None = None) -> list[Skill]:
    """Fetch a source and install every SKILL.md it contains."""
    kind, target, frag = parse_source(source)
    subpath = subpath or frag
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        if kind == "git":
            root, subpath = _fetch_git(target, subpath, workdir)
        elif kind == "npm":
            root, subpath = _fetch_npm(target, workdir)
        elif kind == "archive":
            root = workdir / "src"
            _safe_extract(_download(target), root)
        else:  # path
            root = Path(target)
        skill_files = _find_skill_files(root, subpath)
        if not skill_files:
            raise InvalidSource("no SKILL.md found in source")
        return [_install_one(path.parent, source) for path in skill_files]


def _load(skill_dir: Path) -> Skill:
    meta = {}
    meta_path = skill_dir / _META_FILE
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except ValueError:
            meta = {}
    skill_md = next(
        (p for p in skill_dir.iterdir() if p.name.lower() == "skill.md"), None
    )
    raw = skill_md.read_text(errors="replace") if skill_md else ""
    parsed_meta, body = parse_frontmatter(raw)
    name = meta.get("name") or parsed_meta.get("name") or skill_dir.name
    description = (
        meta.get("description") or parsed_meta.get("description") or _first_line(body)
    )
    return Skill(
        slug=skill_dir.name,
        name=name,
        description=description,
        source=meta.get("source", "local"),
        body=body,
    )


def list_installed() -> list[Skill]:
    return [_load(d) for d in sorted(skills_dir().iterdir()) if d.is_dir()]


def get(slug: str) -> Skill:
    skill_dir = skills_dir() / slug
    if not skill_dir.is_dir():
        raise InvalidSource(f"skill not found: {slug}")
    return _load(skill_dir)


def read(name_or_slug: str) -> str:
    for skill in list_installed():
        if name_or_slug in (skill.slug, skill.name):
            return skill.body
    raise InvalidSource(f"skill not found: {name_or_slug}")


def remove(slug: str) -> None:
    skill_dir = skills_dir() / slug
    if not skill_dir.is_dir():
        raise InvalidSource(f"skill not found: {slug}")
    shutil.rmtree(skill_dir)


def summary() -> str:
    """Markdown list of installed skills for the agent system prompt."""
    skills = list_installed()
    if not skills:
        return ""
    lines = [
        "## Skills",
        "Installed skills extend what you can do. When a skill's description "
        "matches the task, load its full instructions first with read_skill.",
    ]
    lines += [f"- {s.name}: {s.description}" for s in skills]
    return "\n".join(lines)
