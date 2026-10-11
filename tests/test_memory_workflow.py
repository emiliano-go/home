"""Memory workflow: file-tool auto-registration and export/import tools."""

from hestia import totem_store
from hestia.tools import editing, memory
from hestia.tools.registry import ProjectContext, Registry


def _context(root, project_id=1):
    return ProjectContext(project_id=project_id, name="t", repo_url="", local_path=root, write_mode="auto")


def test_edit_auto_registers_implementation_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TOTEM_USER_DB", str(tmp_path / "data" / "totem-user.db"))
    monkeypatch.setenv("HESTIA_MEMORY_AUTOREGISTER", "1")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")

    registry = Registry()
    editing.register(registry, None)
    registry.get("edit").handler(_context(repo), {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})

    items = totem_store.search(repo, "a.py", limit=5)
    assert items


def test_autoregister_off_by_default_without_totem(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("HESTIA_MEMORY_AUTOREGISTER", raising=False)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")

    registry = Registry()
    editing.register(registry, None)
    registry.get("edit").handler(_context(repo), {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})

    assert not (repo / ".totem").exists()


def test_memory_export_import_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TOTEM_USER_DB", str(tmp_path / "data" / "totem-user.db"))

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    totem_store.create(src, "gotcha", "Watch the boundary", "Off-by-one here before.", ["x"])

    registry = Registry()
    memory.register(registry)
    archive = registry.get("memory_export").handler(_context(src), {})
    assert archive["items"]

    report = registry.get("memory_import").handler(_context(dst, project_id=2), {"data": archive})
    assert report.get("items_imported", 0) >= 1
    assert totem_store.list_all(dst, limit=10)
