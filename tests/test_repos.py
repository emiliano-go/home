"""Multi-repo: model, migration backfill, and repo helpers."""

import os

from sqlmodel import Session, select

from hestia.registry.db import _migrate, engine, init_db
from hestia.registry.models import Project, ProjectRepo


def _fresh(tmp_path, monkeypatch):
    import hestia.registry.db as db_mod

    os.environ["DATA_DIR"] = str(tmp_path / "data")
    monkeypatch.setattr(db_mod, "_engine", None)
    init_db()


def test_backfill_creates_primary_repo(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with Session(engine()) as db:
        project = Project(
            name="legacy", repo_url="https://github.com/a/b", local_path="/tmp/clone"
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
        # simulate a pre-migration row set
        for row in db.exec(select(ProjectRepo)).all():
            db.delete(row)
        db.commit()

    _migrate()
    with Session(engine()) as db:
        rows = db.exec(select(ProjectRepo).where(ProjectRepo.project_id == project_id)).all()
        assert len(rows) == 1
        assert rows[0].alias == "main" and rows[0].is_primary
        assert rows[0].repo_url == "https://github.com/a/b"
        assert rows[0].local_path == "/tmp/clone"

    _migrate()  # idempotent
    with Session(engine()) as db:
        assert len(db.exec(select(ProjectRepo)).all()) == 1


def test_workspace_only_project_gets_no_repo(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with Session(engine()) as db:
        project = Project(name="notes")
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
    _migrate()
    with Session(engine()) as db:
        assert db.exec(select(ProjectRepo).where(ProjectRepo.project_id == project_id)).all() == []


import subprocess
from pathlib import Path

import pytest

from hestia import config, repos
from hestia.tools.registry import ProjectContext


def _git_repo(tmp_path, name="src"):
    src = tmp_path / name
    src.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    (src / "README.md").write_text("# x\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
         "commit", "-qm", "i"],
        cwd=src, check=True,
    )
    return src


def test_add_remove_repo_and_context(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    src_a = _git_repo(tmp_path, "a")
    src_b = _git_repo(tmp_path, "b")
    with Session(engine()) as db:
        project = Project(name="multi")
        db.add(project)
        db.commit()
        db.refresh(project)

        first = repos.add_repo(db, project, "main", str(src_a))
        assert first.is_primary
        second = repos.add_repo(db, project, "web", str(src_b))
        assert not second.is_primary
        assert project.local_path == str(repos.clone_dir("multi", "main"))

        ctx = ProjectContext.from_project(project)
        assert [r.alias for r in ctx.repos] == ["main", "web"]
        assert ctx.repo_path("web") == Path(second.local_path)
        assert ctx.repo_path() == Path(first.local_path)
        assert ctx.memory_path == Path(first.local_path)
        with pytest.raises(ValueError, match="unknown repo"):
            ctx.repo_path("nope")

        repos.remove_repo(db, project, "main")
        rows = repos.repos_for(db, project.id)
        assert [r.alias for r in rows] == ["web"] and rows[0].is_primary
        assert project.local_path == str(repos.clone_dir("multi", "web"))

        repos.remove_repo(db, project, "web")
        assert project.repo_url == "" and project.local_path == ""


def test_workspace_only_context(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    with Session(engine()) as db:
        project = Project(name="notes")
        db.add(project)
        db.commit()
        db.refresh(project)
        ctx = ProjectContext.from_project(project)
    assert not ctx.has_repos
    assert ctx.memory_path == config.workspace_dir("notes")
    with pytest.raises(ValueError, match="no repositories"):
        ctx.repo_path()


def test_default_alias():
    assert repos.default_alias("https://github.com/a/Cool_Repo.git", set()) == "cool_repo"
    assert repos.default_alias("https://github.com/a/x", {"x"}) == "x-2"
    assert repos.valid_alias("api-v2") and not repos.valid_alias("Bad Alias")


def test_alias_aware_tools_and_repo_add(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    src_a = _git_repo(tmp_path, "a")
    src_b = _git_repo(tmp_path, "b")
    (src_b / "NOTES.md").write_text("web repo\n")
    subprocess.run(["git", "-C", str(src_b), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(src_b), "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-qm", "n"],
        check=True,
    )
    from hestia.tools import build_registry

    with Session(engine()) as db:
        project = Project(name="multi")
        db.add(project)
        db.commit()
        db.refresh(project)
        repos.add_repo(db, project, "api", str(src_a))
        repos.add_repo(db, project, "web", str(src_b))
        ctx = ProjectContext.from_project(project)
        tools = {t.name: t for t in build_registry(db=db).all()}

        assert tools["list_files"].handler(ctx, {}) == ["README.md"]
        assert set(tools["list_files"].handler(ctx, {"repo": "web"})) == {"NOTES.md", "README.md"}
        content = tools["read_file"].handler(ctx, {"repo": "web", "path": "NOTES.md"})
        assert "web repo" in content["content"]
        with pytest.raises(ValueError, match="unknown repo"):
            tools["list_files"].handler(ctx, {"repo": "nope"})

        listing = tools["repo_list"].handler(ctx, {})
        assert [r["alias"] for r in listing] == ["api", "web"]
        assert listing[0]["primary"] and not listing[1]["primary"]

        project2 = Project(name="empty")
        db.add(project2)
        db.commit()
        db.refresh(project2)
        ctx2 = ProjectContext.from_project(project2)
        first = tools["repo_add"].handler(ctx2, {"url": str(src_a), "alias": "main"})
        assert first["primary"] and first["alias"] == "main"
        src_c = _git_repo(tmp_path, "cool_repo")
        second = tools["repo_add"].handler(ctx2, {"url": str(src_c)})
        assert second["alias"] == "cool_repo" and not second["primary"]


def test_new_session_ids_are_uuid(tmp_path, monkeypatch):
    import uuid

    from hestia.registry.models import Session as ChatSession

    _fresh(tmp_path, monkeypatch)
    with Session(engine()) as db:
        chat = ChatSession(project_id=1)
        db.add(chat)
        db.commit()
        db.refresh(chat)
        uuid.UUID(chat.id)  # raises if not a UUID


def test_session_id_migration_rebuilds_integer_pk(tmp_path, monkeypatch):
    from hestia.registry.models import Session as ChatSession

    _fresh(tmp_path, monkeypatch)
    # simulate a legacy DB whose session table has an INTEGER primary key
    with engine().begin() as conn:
        conn.exec_driver_sql("DROP TABLE session")
        conn.exec_driver_sql(
            "CREATE TABLE session ("
            "id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, "
            "action TEXT DEFAULT 'chat', created_at DATETIME, updated_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO session (id, project_id, title, action, created_at, updated_at) "
            "VALUES (7, 1, 'legacy', 'chat', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )

    _migrate()
    with Session(engine()) as db:
        chat = db.get(ChatSession, "7")
        assert chat is not None and chat.title == "legacy"

    # a second pass must not rebuild again (an index would be dropped)
    with engine().begin() as conn:
        conn.exec_driver_sql("CREATE INDEX keep_idx ON session (title)")
    _migrate()
    with engine().begin() as conn:
        still = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='keep_idx'"
        ).fetchall()
        assert still
    with Session(engine()) as db:
        assert db.get(ChatSession, "7") is not None


def test_github_host_credential_boundary():
    from hestia import urls

    assert urls.github_host("https://github.com/a/b")
    assert not urls.github_host("https://github.com.attacker.example/a/b")
    assert not urls.github_host("https://evil.com/github.com/a/b")
    assert not urls.github_host("http://github.com/a/b")  # token only over https
    assert not urls.github_host("https://api.github.com/repos/a/b")
    assert urls.github_slug("https://github.com/a/b.git") == "a/b"
    assert urls.github_slug("https://github.com.attacker.example/a/b") is None
    assert urls.github_slug("https://evil.com/github.com/a/b") is None

    from hestia import repos as repos_mod

    original = repos_mod.config.github_token
    repos_mod.config.github_token = lambda: "tok"
    try:
        assert repos_mod.auth_args("https://github.com.attacker.example/a/b") == []
        assert repos_mod.auth_args("https://github.com/a/b") != []
    finally:
        repos_mod.config.github_token = original
