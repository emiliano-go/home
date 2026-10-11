"""AGENTS.md instruction hierarchy."""

from hestia.agent import instructions


def test_root_and_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HESTIA_INSTRUCTIONS", raising=False)
    (tmp_path / "AGENTS.md").write_text("root rules")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "AGENTS.md").write_text("nested rules")

    out = instructions.load(tmp_path)
    assert "root rules" in out
    assert "nested rules" in out
    assert "src/AGENTS.md" in out


def test_fallback_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HESTIA_INSTRUCTIONS", raising=False)
    assert instructions.load(tmp_path, fallback="snapshot") == "snapshot"


def test_global_and_env_extras(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "AGENTS.md").write_text("global rules")
    monkeypatch.setenv("DATA_DIR", str(data))
    extra = tmp_path / "extra.md"
    extra.write_text("extra rules")
    monkeypatch.setenv("HESTIA_INSTRUCTIONS", str(extra))

    out = instructions.load(None)
    assert "global rules" in out
    assert "extra rules" in out
