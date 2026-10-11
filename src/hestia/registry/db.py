"""Registry database access (SQLModel over Turso at $DATA_DIR/hestia.db).

Turso is the default engine (shared sqlite-compatible format with totem/encoder,
`multiprocess_wal` for the API + background worker + scheduler). Set
`HESTIA_DB_DRIVER=sqlite` to fall back to the stdlib sqlite3 driver.
"""

import os
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.dialects import registry as _dialect_registry
from sqlmodel import SQLModel, Session, create_engine

from hestia import config

_dialect_registry.register("sqlite+turso", "hestia.registry.turso_dialect", "TursoDialect")

_engine = None


def _driver() -> str:
    return os.environ.get("HESTIA_DB_DRIVER", "turso").strip().lower()


def engine():
    global _engine
    if _engine is None:
        data_dir = config.data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        new_db = data_dir / "hestia.db"
        legacy_db = data_dir / "home.db"
        if legacy_db.exists() and not new_db.exists():
            legacy_db.rename(new_db)  # one-time rename from the old app name
        if _driver() == "sqlite":
            _engine = create_engine(
                f"sqlite:///{new_db}",
                echo=False,
                connect_args={"check_same_thread": False},  # background job workers
            )
        else:
            _engine = create_engine(f"sqlite+turso:///{new_db}", echo=False)
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(engine())
    _migrate()


def _migrate() -> None:
    """Add columns missing from pre-existing SQLite tables (create_all never alters)."""
    with engine().begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(project)")}
        if columns and "last_opened_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE project ADD COLUMN last_opened_at DATETIME")
        if columns and "allow_git_writes" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE project ADD COLUMN allow_git_writes BOOLEAN DEFAULT 0"
            )
        if columns and "write_mode" not in columns:
            conn.exec_driver_sql("ALTER TABLE project ADD COLUMN write_mode TEXT DEFAULT ''")
        if columns and "token_budget" not in columns:
            conn.exec_driver_sql("ALTER TABLE project ADD COLUMN token_budget INTEGER")
        if columns and "budget_enforced" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE project ADD COLUMN budget_enforced BOOLEAN DEFAULT 0"
            )
        if columns and "require_write_approval" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE project ADD COLUMN require_write_approval BOOLEAN DEFAULT 0"
            )
        if columns and "allow_local_browser" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE project ADD COLUMN allow_local_browser BOOLEAN DEFAULT 0"
            )
        if columns and "require_plan" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE project ADD COLUMN require_plan BOOLEAN DEFAULT 0"
            )
        if columns and "description" not in columns:
            conn.exec_driver_sql("ALTER TABLE project ADD COLUMN description TEXT DEFAULT ''")

        task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(task)")}
        if task_columns and "milestone_id" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN milestone_id INTEGER")
        if task_columns and "depends_on" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN depends_on TEXT DEFAULT '[]'")
        if task_columns and "acceptance" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN acceptance TEXT DEFAULT ''")
        if task_columns and "github_issue" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN github_issue INTEGER")
        if task_columns and "source" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN source TEXT DEFAULT 'user'")
        if task_columns and "due_at" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN due_at DATETIME")
        if task_columns and "pr_url" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN pr_url TEXT")
        if task_columns and "repo" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN repo TEXT")

        question_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(question)")}
        if question_columns and "kind" not in question_columns:
            conn.exec_driver_sql("ALTER TABLE question ADD COLUMN kind TEXT DEFAULT 'question'")
        if question_columns and "meta" not in question_columns:
            conn.exec_driver_sql("ALTER TABLE question ADD COLUMN meta TEXT DEFAULT '{}'")

        session_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(session)")}
        if session_columns and "action" not in session_columns:
            conn.exec_driver_sql("ALTER TABLE session ADD COLUMN action TEXT DEFAULT 'chat'")
        # Session ids became UUID strings; SQLite cannot alter a column type, so
        # rebuild the table once and keep existing ids as their string form.
        id_type = conn.exec_driver_sql(
            "SELECT type FROM pragma_table_info('session') WHERE name='id'"
        ).fetchone()
        declared = (id_type[0] or "").upper() if id_type else ""
        # SQLAlchemy emits VARCHAR for string PKs on SQLite; only rebuild for
        # the legacy integer primary key.
        if session_columns and declared and not any(t in declared for t in ("TEXT", "CHAR", "CLOB")):
            rows = conn.exec_driver_sql(
                "SELECT id, project_id, title, action, created_at, updated_at FROM session"
            ).fetchall()
            conn.exec_driver_sql("DROP TABLE session")
            SQLModel.metadata.tables["session"].create(conn, checkfirst=False)
            for row in rows:
                conn.exec_driver_sql(
                    "INSERT INTO session (id, project_id, title, action, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(row[0]), row[1], row[2], row[3], row[4], row[5]),
                )

        provider_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(provider)")}
        if provider_columns and "api_key" not in provider_columns:
            conn.exec_driver_sql("ALTER TABLE provider ADD COLUMN api_key TEXT")
        if provider_columns and "keys" not in provider_columns:
            conn.exec_driver_sql("ALTER TABLE provider ADD COLUMN keys TEXT DEFAULT '[]'")
        if provider_columns and "key_state" not in provider_columns:
            conn.exec_driver_sql("ALTER TABLE provider ADD COLUMN key_state TEXT DEFAULT '{}'")
        if provider_columns and "small_model" not in provider_columns:
            conn.exec_driver_sql("ALTER TABLE provider ADD COLUMN small_model TEXT DEFAULT ''")
        if provider_columns and "models" not in provider_columns:
            conn.exec_driver_sql("ALTER TABLE provider ADD COLUMN models TEXT DEFAULT '[]'")
            # seed the list from the existing single default model
            conn.exec_driver_sql(
                "UPDATE provider SET models = '[\"' || model || '\"]' "
                "WHERE (models IS NULL OR models = '[]') AND model IS NOT NULL AND model != ''"
            )

        agent_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agentconfig)")}
        if agent_columns and "model" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE agentconfig ADD COLUMN model TEXT")
        if agent_columns and "mode" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE agentconfig ADD COLUMN mode TEXT DEFAULT 'read'")
            # profiles that can already write workspace/memory become write mode
            conn.exec_driver_sql(
                "UPDATE agentconfig SET mode = 'write' "
                "WHERE tools LIKE '%workspace%' OR tools LIKE '%memory%'"
            )
        if agent_columns and "reasoning_effort" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE agentconfig ADD COLUMN reasoning_effort TEXT")

        msg_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(message)")}
        if msg_columns and "thinking" not in msg_columns:
            conn.exec_driver_sql("ALTER TABLE message ADD COLUMN thinking TEXT")

        bt_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(backgroundtask)")}
        if bt_columns and "payload" not in bt_columns:
            conn.exec_driver_sql("ALTER TABLE backgroundtask ADD COLUMN payload TEXT DEFAULT '{}'")

        message_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(message)")}
        if message_columns and "tool_call_id" not in message_columns:
            conn.exec_driver_sql("ALTER TABLE message ADD COLUMN tool_call_id TEXT")
        if message_columns and "ok" not in message_columns:
            conn.exec_driver_sql("ALTER TABLE message ADD COLUMN ok BOOLEAN")

        inbox_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(inboxitem)")}
        if inbox_columns and "repo" not in inbox_columns:
            conn.exec_driver_sql("ALTER TABLE inboxitem ADD COLUMN repo TEXT DEFAULT ''")

        # Backfill one primary ProjectRepo per legacy single-repo project.
        repo_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(projectrepo)")}
        if repo_columns:
            legacy = conn.exec_driver_sql(
                "SELECT id, repo_url, local_path FROM project WHERE repo_url != ''"
            ).fetchall()
            for project_id, repo_url, local_path in legacy:
                existing = conn.exec_driver_sql(
                    "SELECT COUNT(*) FROM projectrepo WHERE project_id = ?", (project_id,)
                ).scalar()
                if not existing:
                    conn.exec_driver_sql(
                        "INSERT INTO projectrepo "
                        "(project_id, alias, repo_url, local_path, is_primary, created_at) "
                        "VALUES (?, 'main', ?, ?, 1, ?)",
                        (
                            project_id,
                            repo_url,
                            local_path or "",
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )

        schedule_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(schedule)")}
        if schedule_columns and "trigger" not in schedule_columns:
            conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN trigger TEXT DEFAULT 'interval'")
        if schedule_columns and "event" not in schedule_columns:
            conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN event TEXT DEFAULT ''")
        if schedule_columns and "event_filter" not in schedule_columns:
            conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN event_filter TEXT DEFAULT ''")
        if schedule_columns and "cooldown_minutes" not in schedule_columns:
            conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN cooldown_minutes INTEGER DEFAULT 0")
        if schedule_columns and "last_event_key" not in schedule_columns:
            conn.exec_driver_sql("ALTER TABLE schedule ADD COLUMN last_event_key TEXT DEFAULT ''")


def session() -> Iterator[Session]:
    with Session(engine()) as s:
        yield s
