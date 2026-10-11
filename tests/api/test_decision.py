"""Decision engine HTTP endpoints."""

import json
import subprocess
import tempfile
from pathlib import Path

from hestia.decision import config


def test_get_and_patch_decision(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "state_file", lambda: tmp_path / "decision.json")
    assert client.get("/api/decision").json()["enabled"] is False

    resp = client.patch("/api/decision", json={"enabled": True, "baseUrl": "http://laya:8765"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["hasBaseUrl"] is True
    assert client.get("/api/decision").json()["enabled"] is True


def test_project_evaluations_reads_log(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "state_file", lambda: tmp_path / "decision.json")

    src = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    (Path(src) / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "i"],
        cwd=src,
        check=True,
    )
    project = client.post("/api/projects", json={"name": "demo", "repo_url": src}).json()

    root = Path(project.get("local_path") or src)
    log_dir = root / ".encoder"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "decision-log.jsonl").write_text(json.dumps({"time": 1, "kind": "mutation", "verdict": "fail", "composite": 0.4}) + "\n")

    resp = client.get(f"/api/projects/{project['id']}/decision/evaluations")
    assert resp.status_code == 200
    assert resp.json()[0]["verdict"] == "fail"
