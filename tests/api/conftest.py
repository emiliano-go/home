"""Shared fixtures and helpers for the API tests."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hestia import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    os.environ["DATA_DIR"] = str(tmp_path / "data")
    # isolate Totem user memory (identity/preferences) per test
    monkeypatch.setenv("TOTEM_USER_DB", str(tmp_path / "data" / "totem-user.db"))
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    import hestia.registry.db as db

    monkeypatch.setattr(db, "_engine", None)

    from hestia.main import create_app

    return TestClient(create_app())


def _mk_project(client, name="demo", repo_url=None):
    import subprocess, tempfile

    src = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    (Path(src) / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "i"], cwd=src, check=True)
    resp = client.post("/api/projects", json={"name": name, "repo_url": repo_url or src})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _mk_provider(client, name="p"):
    return client.post("/api/providers", json={
        "name": name, "base_url": "http://x", "api_key_env": "K", "model": "m",
    }).json()
