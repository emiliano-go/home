"""Live browser smoke test: skipped unless HESTIA_BROWSER_TEST=1.

Needs Chromium (bundled via ``browser-use install`` or a system binary via
``HESTIA_BROWSER_EXECUTABLE``). Not part of CI.
"""

import os

import pytest

from hestia.tools import browser as browser_tools
from hestia.tools.registry import ProjectContext

pytestmark = pytest.mark.skipif(
    os.environ.get("HESTIA_BROWSER_TEST") != "1", reason="set HESTIA_BROWSER_TEST=1"
)


def test_live_navigate_screenshot_content(tmp_path):
    ctx = ProjectContext(
        project_id=1,
        name="t",
        repo_url="",
        local_path=tmp_path,
        workspace_path=tmp_path / "ws",
        session_id=1,
    )
    tools = {t.name: t for t in browser_tools.make_tools(None)}
    try:
        opened = tools["browser_open"].handler(ctx, {"url": "https://example.com"})
        assert "example.com" in opened["url"]

        shot = tools["browser_screenshot"].handler(ctx, {})
        assert (ctx.workspace_path / shot["path"]).read_bytes()[:4] == b"\x89PNG"

        content = tools["browser_get_content"].handler(ctx, {})
        assert "documentation" in content["text"].lower()
    finally:
        browser_tools.manager.shutdown()
