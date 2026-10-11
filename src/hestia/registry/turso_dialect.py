"""SQLAlchemy dialect that runs SQLModel/SQLAlchemy over Turso (`pyturso`).

Turso's Python package exposes a sqlite-compatible DBAPI2 at the top level
(`turso.connect`, `Connection`, `Cursor`, `Row`, standard DBAPI exceptions),
so the stdlib pysqlite dialect can drive it. The only adjustments:

- `import_dbapi` returns the `turso` module instead of `sqlite3`;
- `create_connect_args` drops `check_same_thread` (a `sqlite3`-only kwarg
  SQLAlchemy always sets) and opts into `multiprocess_wal`, which is what makes
  the registry safe to share between the API process, background job workers,
  and the scheduler.

Registering the dialect happens in `hestia.registry.db`.
"""

from sqlalchemy.dialects.sqlite import pysqlite


class TursoDialect(pysqlite.SQLiteDialect_pysqlite):
    driver = "turso"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        import turso

        return turso

    def create_connect_args(self, url):
        cargs, cparams = super().create_connect_args(url)
        cparams.pop("check_same_thread", None)
        cparams.pop("uri", None)
        cparams.setdefault("experimental_features", "multiprocess_wal")
        return cargs, cparams
