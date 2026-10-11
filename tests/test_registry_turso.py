"""The registry runs on Turso by default (sqlite-compatible, multiprocess WAL)."""

import pytest

from hestia.registry import db


@pytest.fixture(autouse=True)
def _reset_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HESTIA_DB_DRIVER", raising=False)
    monkeypatch.setattr(db, "_engine", None)
    yield
    monkeypatch.setattr(db, "_engine", None)


def test_engine_defaults_to_turso(tmp_path):
    engine = db.engine()
    assert engine.url.drivername == "sqlite+turso"
    assert engine.dialect.driver == "turso"
    db.init_db()
    assert (tmp_path / "hestia.db").exists()


def test_sqlite_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("HESTIA_DB_DRIVER", "sqlite")
    engine = db.engine()
    assert engine.url.drivername == "sqlite"
