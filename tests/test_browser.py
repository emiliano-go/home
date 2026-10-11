"""Browser tools: guard, manager lifecycle, tools (browser-use mocked)."""

import base64
import time

import pytest

from hestia.tools import browser as browser_tools
from hestia.tools.registry import ProjectContext
from hestia.webfetch import FetchError

PNG = b"\x89PNG\r\n\x1a\nfakepng"


class FakePage:
    def __init__(self):
        self.typed = []
        self.clicked = []
        self.scripts = []

    async def get_url(self):
        return "https://example.com/"

    async def get_title(self):
        return "Example"

    async def screenshot(self, format="png", quality=None):
        return base64.b64encode(PNG).decode()

    async def evaluate(self, script, *args):
        self.scripts.append(script)
        if "innerText" in script:
            return "page text"
        if "querySelectorAll" in script:
            return True
        return "eval-result"

    async def get_elements_by_css_selector(self, selector):
        return [FakeElement(self)]


class FakeElement:
    def __init__(self, page):
        self.page = page

    async def click(self):
        self.page.clicked.append(self)

    async def fill(self, value, clear=True):
        self.page.typed.append(value)


class FakeBrowser:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.killed = False
        self.closed = False
        self.page = FakePage()

    async def start(self):
        self.started = True

    async def kill(self):
        self.killed = True

    async def close(self):
        self.closed = True

    async def navigate_to(self, url, new_tab=False):
        self.url = url

    async def must_get_current_page(self):
        return self.page


class FakeModule:
    Browser = FakeBrowser


def test_guard_blocks_local_by_default(monkeypatch):
    monkeypatch.setattr(browser_tools.webfetch.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(FetchError):
        browser_tools.validate_url("http://localhost:5173")
    # explicit per-project opt-in allows loopback
    assert browser_tools.validate_url("http://localhost:5173", allow_local=True)


def test_guard_blocks_metadata_even_with_allow_local(monkeypatch):
    monkeypatch.setattr(
        browser_tools.webfetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(FetchError):
        browser_tools.validate_url("http://metadata.test", allow_local=True)


def test_guard_rejects_non_http():
    with pytest.raises(FetchError):
        browser_tools.validate_url("file:///etc/passwd", allow_local=True)


def test_manager_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_tools, "_load", lambda: FakeModule)
    mgr = browser_tools.BrowserManager()
    try:
        first = mgr.ensure("s1", headless=True, downloads=tmp_path)
        assert first.started
        assert first.kwargs["downloads_path"] == str(tmp_path)
        assert first.kwargs["prohibited_domains"]

        again = mgr.ensure("s1", headless=True)
        assert again is first  # persistent per session

        other = mgr.ensure("s2", headless=True, cdp_url="http://localhost:9222")
        assert other.kwargs["cdp_url"] == "http://localhost:9222"

        mgr.close("s2")  # CDP attach: disconnect, never kill the owner's Chrome
        assert other.closed and not other.killed

        mgr.close("s1")
        assert first.killed
    finally:
        mgr.shutdown()


def test_manager_reaps_idle_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_tools, "_load", lambda: FakeModule)
    mgr = browser_tools.BrowserManager()
    try:
        b = mgr.ensure("s1", headless=True)
        mgr._last_used["s1"] = time.monotonic() - browser_tools.IDLE_SECONDS - 1
        # a new session triggers the reap pass
        mgr.ensure("s2", headless=True)
        assert b.killed
    finally:
        mgr.shutdown()


@pytest.fixture
def fake_manager(monkeypatch):
    monkeypatch.setattr(browser_tools, "_load", lambda: FakeModule)
    mgr = browser_tools.BrowserManager()
    monkeypatch.setattr(browser_tools, "manager", mgr)
    yield mgr
    mgr.shutdown()


def _ctx(tmp_path, allow_local=False):
    return ProjectContext(
        project_id=3,
        name="t",
        repo_url="",
        local_path=tmp_path,
        workspace_path=tmp_path / "ws",
        session_id=7,
        allow_local_browser=allow_local,
    )


def test_tools_register_effects_and_delegation(fake_manager):
    tools = {t.name: t for t in browser_tools.make_tools(None)}
    assert set(tools) == {
        "browser_task",
        "browser_open",
        "browser_screenshot",
        "browser_get_content",
        "browser_click",
        "browser_type",
        "browser_eval",
        "browser_close",
    }
    for tool in tools.values():
        assert tool.group == "browser" and tool.delegable is False
    assert tools["browser_open"].effect == "read"
    assert tools["browser_screenshot"].effect == "read"
    assert tools["browser_get_content"].effect == "read"
    assert tools["browser_click"].effect == "write"
    assert tools["browser_eval"].effect == "write"
    assert tools["browser_task"].effect == "write"


def test_open_screenshot_and_content(fake_manager, tmp_path):
    tools = {t.name: t for t in browser_tools.make_tools(None)}
    ctx = _ctx(tmp_path)

    opened = tools["browser_open"].handler(ctx, {"url": "https://example.com"})
    assert opened["title"] == "Example"

    shot = tools["browser_screenshot"].handler(ctx, {})
    assert shot["path"].startswith("browser/screenshot-")
    assert (ctx.workspace_path / shot["path"]).read_bytes() == PNG
    assert shot["markdown"].startswith("![")

    text = tools["browser_get_content"].handler(ctx, {})
    assert text["text"] == "page text"

    typed = tools["browser_type"].handler(ctx, {"selector": "#q", "text": "hi"})
    assert typed["result"] == "typed"
    clicked = tools["browser_click"].handler(ctx, {"selector": "#go"})
    assert clicked["result"] == "clicked"
    evaluated = tools["browser_eval"].handler(ctx, {"script": "1 + 1"})
    assert evaluated["result"] == "eval-result"

    tools["browser_close"].handler(ctx, {})
    assert fake_manager._browsers == {}


def test_open_blocked_by_guard(fake_manager, tmp_path, monkeypatch):
    monkeypatch.setattr(
        browser_tools.webfetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    tools = {t.name: t for t in browser_tools.make_tools(None)}
    with pytest.raises(FetchError):
        tools["browser_open"].handler(_ctx(tmp_path), {"url": "http://localhost:5173"})
    # per-project opt-in allows it
    tools["browser_open"].handler(
        _ctx(tmp_path, allow_local=True), {"url": "http://localhost:5173"}
    )


def test_browser_disabled_setting(fake_manager, tmp_path, monkeypatch):
    from hestia import settings

    monkeypatch.setattr(settings, "get_bool", lambda db, key, default=False: False)
    tools = {t.name: t for t in browser_tools.make_tools(None, db=object())}
    with pytest.raises(ValueError, match="disabled"):
        tools["browser_open"].handler(_ctx(tmp_path), {"url": "https://example.com"})


def _make_reader_db(tmp_path, monkeypatch):
    import os

    from sqlmodel import Session

    import hestia.registry.db as db_mod
    from hestia.registry.db import engine, init_db
    from hestia.registry.models import ActionDefault, AgentConfig, Provider

    os.environ["DATA_DIR"] = str(tmp_path / "data")
    monkeypatch.setattr(db_mod, "_engine", None)
    init_db()
    session = Session(engine())
    provider = Provider(name="reader", base_url="http://x", api_key_env="NOPE", model="m")
    session.add(provider)
    session.commit()
    session.refresh(provider)
    agent = AgentConfig(
        name="image-reader", provider_id=provider.id, tools="browser", mode="read", max_turns=2
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    session.add(ActionDefault(action="image-reader", agent_id=agent.id))
    session.commit()
    return session


def test_screenshot_auto_describe_with_reader(fake_manager, tmp_path, monkeypatch):
    from hestia.agent import loop as agent_loop

    captured = {}

    async def fake_run_turn(ctx, client, registry, messages, max_turns=10):
        captured["messages"] = messages
        captured["tools"] = {t.name for t in registry.all()}
        yield {"type": "message", "content": "A login form with a red error banner.", "tool_calls": []}

    monkeypatch.setattr(agent_loop, "run_turn", fake_run_turn)
    db = _make_reader_db(tmp_path, monkeypatch)
    try:
        tools = {t.name: t for t in browser_tools.make_tools(None, db)}
        ctx = _ctx(tmp_path)
        result = tools["browser_screenshot"].handler(ctx, {"question": "what is broken?"})
    finally:
        db.close()

    assert result["description"] == "A login form with a red error banner."
    assert result["path"].startswith("browser/screenshot-")
    user = captured["messages"][-1]["content"]
    assert user[0] == {"type": "text", "text": "what is broken?"}
    assert user[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # the reader can look, never act
    assert not captured["tools"] & {
        "browser_click",
        "browser_type",
        "browser_eval",
        "browser_close",
        "browser_task",
    }
    assert {"browser_open", "browser_screenshot", "browser_get_content"} <= captured["tools"]


def test_screenshot_without_reader_is_just_an_image(fake_manager, tmp_path, monkeypatch):
    import os

    from sqlmodel import Session

    import hestia.registry.db as db_mod
    from hestia.registry.db import engine, init_db

    os.environ["DATA_DIR"] = str(tmp_path / "data2")
    monkeypatch.setattr(db_mod, "_engine", None)
    init_db()
    with Session(engine()) as db:
        tools = {t.name: t for t in browser_tools.make_tools(None, db)}
        result = tools["browser_screenshot"].handler(_ctx(tmp_path), {"question": "hi"})
    assert "description" not in result


def test_eval_wraps_plain_expression(fake_manager, tmp_path):
    tools = {t.name: t for t in browser_tools.make_tools(None)}
    ctx = _ctx(tmp_path)
    tools["browser_eval"].handler(ctx, {"script": "document.title"})
    browser = fake_manager._browsers[browser_tools.session_key(ctx)]
    assert browser.page.scripts[-1] == "() => (document.title)"

    # an explicit arrow function is passed through untouched
    tools["browser_eval"].handler(ctx, {"script": "() => { return 1; }"})
    assert browser.page.scripts[-1] == "() => { return 1; }"
