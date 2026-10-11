"""Browser tools (browser-use): autonomous web tasks and UI debugging.

Principal-only: browser automation has external side effects. A dedicated
worker thread owns the asyncio loop and one persistent browser per chat
session; tool handlers bridge to it with ``run_coroutine_threadsafe`` so
browser work never blocks the server event loop.

browser-use is an optional dependency (``uv sync --extra browser``): when it
is not importable, or ``HESTIA_BROWSER`` is off, the tools are not registered.

SSRF: every explicit navigation is validated like the web_fetch tool; private
addresses are rejected unless the project sets ``allow_local_browser``.
browser-use drives Chromium over CDP, so subresource requests are not
intercepted; the cloud metadata hosts are blocked via ``prohibited_domains``
and the final URL is checked after autonomous runs.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from hestia import config, webfetch
from hestia.tools.registry import Tool, schema

PROHIBITED_HOSTS = [
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.goog",
]
IDLE_SECONDS = 600
START_TIMEOUT = 120.0
RUN_TIMEOUT = 300.0


def _load():
    """Import browser_use lazily; tests monkeypatch this."""
    import browser_use

    return browser_use


def available() -> bool:
    if not config.browser_enabled():
        return False
    try:
        _load()
    except ImportError:
        return False
    return True


def validate_url(url: str, allow_local: bool = False) -> str:
    """SSRF guard for explicit navigations, shared with the web_fetch rules."""
    return webfetch._validate((url or "").strip(), allow_local=allow_local)


class BrowserManager:
    """One worker thread + event loop; persistent browsers keyed by chat session."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._browsers: dict[str, Any] = {}
        self._last_used: dict[str, float] = {}
        self._cdp: dict[str, bool] = {}
        self._lock = threading.Lock()

    def _ensure_loop(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, name="hestia-browser", daemon=True
            )
            self._thread.start()

    def run(self, coro, timeout: float = RUN_TIMEOUT):
        """Run a coroutine on the browser loop and wait for the result."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _ensure_browser(self, key: str, opts: dict) -> Any:
        await self._reap()
        browser = self._browsers.get(key)
        if browser is None:
            browser_use = _load()
            kwargs: dict[str, Any] = {
                "headless": opts.get("headless", True),
                "keep_alive": True,
                "prohibited_domains": PROHIBITED_HOSTS,
            }
            if opts.get("downloads"):
                kwargs["downloads_path"] = str(opts["downloads"])
            if opts.get("executable"):
                kwargs["executable_path"] = opts["executable"]
            if opts.get("cdp_url"):
                kwargs["cdp_url"] = opts["cdp_url"]
            if opts.get("allowed_domains"):
                kwargs["allowed_domains"] = opts["allowed_domains"]
            browser = browser_use.Browser(**kwargs)
            await browser.start()
            self._browsers[key] = browser
            self._cdp[key] = bool(opts.get("cdp_url"))
        self._last_used[key] = time.monotonic()
        return browser

    async def _close_browser(self, key: str) -> None:
        browser = self._browsers.pop(key, None)
        self._last_used.pop(key, None)
        cdp = self._cdp.pop(key, False)
        if browser is None:
            return
        try:
            if cdp:
                await browser.close()  # attached to the owner's Chrome: disconnect only
            else:
                await browser.kill()
        except Exception:
            pass

    async def _reap(self) -> None:
        now = time.monotonic()
        stale = [k for k, t in self._last_used.items() if now - t > IDLE_SECONDS]
        for key in stale:
            await self._close_browser(key)

    def ensure(self, key: str, **opts) -> Any:
        """The persistent browser for a session, started if needed."""
        return self.run(self._ensure_browser(key, opts), timeout=START_TIMEOUT)

    def close(self, key: str) -> None:
        try:
            self.run(self._close_browser(key), timeout=60.0)
        except Exception:
            pass

    def shutdown(self) -> None:
        if self._loop is None:
            return
        for key in list(self._browsers):
            self.close(key)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._thread = None
        self._loop = None


manager = BrowserManager()


def session_key(ctx) -> str:
    return f"session:{ctx.session_id}" if ctx.session_id else f"project:{ctx.project_id}"


def _save_png(ctx, data_b64: str, prefix: str) -> dict:
    import base64
    from urllib.parse import quote

    root = ctx.workspace_path
    if root is None:
        raise ValueError("project has no workspace")
    root = root.resolve()
    path = root / "browser" / f"{prefix}-{int(time.time() * 1000)}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data_b64))
    rel = str(path.relative_to(root))
    url = f"/api/projects/{ctx.project_id}/workspace/raw?path={quote(rel)}"
    return {"path": rel, "url": url, "markdown": f"![{prefix}]({url})"}


async def _navigate(browser, url: str) -> dict:
    await browser.navigate_to(url)
    page = await browser.must_get_current_page()
    return {"url": await page.get_url(), "title": await page.get_title()}


async def _current_url(browser) -> str:
    page = await browser.must_get_current_page()
    return await page.get_url()


async def _screenshot(browser) -> str:
    page = await browser.must_get_current_page()
    return await page.screenshot(format="png")


async def _content(browser, selector: str | None) -> str:
    page = await browser.must_get_current_page()
    if selector:
        return await page.evaluate(
            "(sel) => { const el = document.querySelector(sel); return el ? el.innerText : null; }",
            selector,
        )
    return await page.evaluate("() => (document.body ? document.body.innerText : '')")


async def _click(browser, selector: str | None, text: str | None) -> str:
    page = await browser.must_get_current_page()
    if selector:
        elements = await page.get_elements_by_css_selector(selector)
        if not elements:
            raise ValueError(f"no element matches selector: {selector}")
        await elements[0].click()
        return "clicked"
    script = (
        "(t) => { const els = [...document.querySelectorAll("
        "'a,button,[role=button],input[type=submit],summary')];"
        " const el = els.find(e => ((e.innerText || e.value || '').trim().toLowerCase())"
        ".includes(t.toLowerCase())); if (!el) return false; el.click(); return true; }"
    )
    ok = await page.evaluate(script, text or "")
    if not ok:
        raise ValueError(f"no clickable element with text: {text}")
    return "clicked"


async def _type(browser, selector: str, text: str) -> str:
    page = await browser.must_get_current_page()
    elements = await page.get_elements_by_css_selector(selector)
    if not elements:
        raise ValueError(f"no element matches selector: {selector}")
    await elements[0].fill(text)
    return "typed"


def _as_function(script: str) -> str:
    """browser-use's evaluate requires (...args) => format; wrap plain expressions."""
    stripped = script.strip()
    if stripped.startswith(("(", "async", "function")):
        return stripped
    return f"() => ({stripped})"


async def _eval(browser, script: str) -> str:
    page = await browser.must_get_current_page()
    return await page.evaluate(_as_function(script))


async def _run_agent(browser, llm, task: str, max_steps: int, use_vision: bool):
    browser_use = _load()
    agent = browser_use.Agent(
        task=task, llm=llm, browser_session=browser, use_vision=use_vision
    )
    return await agent.run(max_steps=max_steps)


def _chat_llm(provider):
    from hestia.providers.base import resolve_api_key

    browser_use = _load()
    return browser_use.ChatOpenAI(
        model=provider.model,
        base_url=f"{provider.base_url.rstrip('/')}/v1",
        api_key=resolve_api_key(provider) or "not-needed",
    )


def _browser_provider(db, fallback):
    """The provider/model for browser runs: the agent assigned to the browser action."""
    if db is None:
        return fallback
    from hestia import actions
    from hestia.registry.models import Provider

    config = actions.resolve_action(db, "browser")
    if config is None:
        return fallback
    provider = db.get(Provider, config.provider_id)
    return actions.effective_provider(config, provider) or fallback


READER_PROMPT = """\
You describe images for another agent working in this project. Answer the
question about the screenshot precisely and briefly (a few sentences). Use
your browser tools only if you need to look at more of the page. Never take
actions or modify anything.

## Compacted conversation
{context}
"""


def _explicit_agent(db, key: str):
    """The agent explicitly assigned to an action, or None (no chat fallback)."""
    if db is None:
        return None
    from hestia.registry.models import ActionDefault, AgentConfig

    row = db.get(ActionDefault, key)
    if row is None or not row.agent_id:
        return None
    return db.get(AgentConfig, row.agent_id)


def _reader_config(db):
    """Reader profile for forced describe: image-reader -> browser -> chat."""
    if db is None:
        return None
    from hestia import actions

    explicit = _explicit_agent(db, "image-reader")
    return explicit if explicit is not None else actions.resolve_action(db, "image-reader")


def _provider_for(db, config, fallback):
    if db is None or config is None:
        return fallback
    from hestia import actions
    from hestia.registry.models import Provider

    provider = db.get(Provider, config.provider_id)
    return actions.effective_provider(config, provider) or fallback


def _describe_image(ctx, db, fallback_provider, png_b64: str, question: str, config) -> str:
    """Run the image-reader agent over one screenshot; returns its text answer."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlmodel import select

    from hestia import usage
    from hestia.agent import loop as agent_loop
    from hestia.agent.prompt import compact_messages
    from hestia.providers.base import OpenAIClient, resolve_api_key
    from hestia.registry.models import Message
    from hestia.tools.registry import Registry

    provider = _provider_for(db, config, fallback_provider)
    context = ""
    if db is not None and ctx.session_id:
        rows = db.exec(
            select(Message).where(Message.session_id == ctx.session_id).order_by(Message.id)
        ).all()
        context = compact_messages(rows)
    system = READER_PROMPT.format(context=context or "(no conversation yet)")
    if config is not None and config.system_prompt:
        system += f"\n\n## Agent instructions\n{config.system_prompt}"
    prompt = question or (
        "Describe this screenshot: layout, visible text, and anything broken, "
        "missing, or noteworthy."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{png_b64}"},
                },
            ],
        },
    ]
    registry = Registry()
    for tool in make_tools(provider, db, describe=False):
        registry.register(tool)
    registry = registry.readonly()  # the reader looks, never clicks or types

    client = OpenAIClient(
        provider.base_url,
        resolve_api_key(provider),
        provider.model,
        session=f"image-reader-{ctx.session_id or ctx.project_id}",
        reasoning_effort=getattr(provider, "reasoning_effort", None),
    )

    async def run() -> tuple[str, dict]:
        final = ""
        tokens: dict = {}
        async for event in agent_loop.run_turn(ctx, client, registry, messages, max_turns=3):
            if event["type"] == "usage":
                usage.merge(tokens, event.get("usage"))
            elif event["type"] == "message":
                final = event.get("content", "") or final
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return final, tokens

    with ThreadPoolExecutor(max_workers=1) as pool:
        final, tokens = pool.submit(asyncio.run, run()).result(timeout=240.0)
    usage.record(
        db,
        ctx.project_id,
        session_id=ctx.session_id,
        action="image-reader",
        model=provider.model,
        usage=tokens,
    )
    return (final or "").strip()


def make_tools(provider, db=None, *, describe: bool = True) -> list[Tool]:
    def enabled() -> bool:
        if not config.browser_enabled():
            return False
        if db is None:
            return True
        from hestia import settings

        try:
            return settings.get_bool(db, "browser_enabled", True)
        except Exception:
            return True

    def opts(ctx) -> dict:
        from hestia import settings

        cdp = config.browser_cdp_url()
        if not cdp and db is not None:
            try:
                cdp = (settings.get(db, "browser_cdp_url") or "").strip() or None
            except Exception:
                cdp = None
        downloads = None
        if ctx.workspace_path is not None:
            downloads = ctx.workspace_path / "browser" / "downloads"
            downloads.mkdir(parents=True, exist_ok=True)
        return {
            "headless": config.browser_headless(),
            "cdp_url": cdp,
            "executable": config.browser_executable(),
            "downloads": downloads,
        }

    def browser_for(ctx):
        if not enabled():
            raise ValueError("browser is disabled in assistant settings")
        return manager.ensure(session_key(ctx), **opts(ctx))

    def open_handler(ctx, args):
        url = validate_url(args.get("url", ""), ctx.allow_local_browser)
        browser = browser_for(ctx)
        return manager.run(_navigate(browser, url), timeout=90.0)

    def screenshot_handler(ctx, args):
        browser = browser_for(ctx)
        data = manager.run(_screenshot(browser), timeout=90.0)
        saved = _save_png(ctx, data, "screenshot")
        if not describe or args.get("describe") is False:
            return saved
        # auto-describe only when an image-reader agent is explicitly assigned;
        # describe=true forces the image-reader -> browser -> chat fallback
        config = (
            _reader_config(db)
            if args.get("describe") is True
            else _explicit_agent(db, "image-reader")
        )
        if config is None:
            return saved
        question = (args.get("question") or "").strip()
        try:
            saved["description"] = _describe_image(ctx, db, provider, data, question, config)
        except Exception as e:  # the screenshot is still saved for the owner
            saved["description_error"] = f"{type(e).__name__}: {e}"[:500]
        return saved

    def content_handler(ctx, args):
        browser = browser_for(ctx)
        text = manager.run(_content(browser, args.get("selector")), timeout=90.0)
        return {"text": (text or "")[:20_000]}

    def click_handler(ctx, args):
        selector = (args.get("selector") or "").strip() or None
        text = (args.get("text") or "").strip() or None
        if not selector and not text:
            raise ValueError("selector or text is required")
        browser = browser_for(ctx)
        return {"result": manager.run(_click(browser, selector, text), timeout=90.0)}

    def type_handler(ctx, args):
        browser = browser_for(ctx)
        return {
            "result": manager.run(
                _type(browser, args["selector"], args.get("text", "")), timeout=90.0
            )
        }

    def eval_handler(ctx, args):
        script = (args.get("script") or "").strip()
        if not script:
            raise ValueError("script is required")
        browser = browser_for(ctx)
        result = manager.run(_eval(browser, script), timeout=90.0)
        return {"result": str(result)[:20_000]}

    def close_handler(ctx, args):
        manager.close(session_key(ctx))
        return {"closed": True}

    def task_handler(ctx, args):
        task = (args.get("task") or "").strip()
        if not task:
            raise ValueError("task is required")
        browser = browser_for(ctx)
        if args.get("url"):
            url = validate_url(args["url"], ctx.allow_local_browser)
            manager.run(_navigate(browser, url), timeout=90.0)
        llm = _chat_llm(_browser_provider(db, provider))
        max_steps = max(1, min(int(args.get("max_steps") or 25), 100))
        use_vision = args.get("vision", True) is not False
        history = manager.run(
            _run_agent(browser, llm, task, max_steps, use_vision), timeout=RUN_TIMEOUT
        )
        images = []
        for data in (history.screenshots(n_last=2) or []):
            if data:
                images.append(_save_png(ctx, data, "task"))
        try:
            final_url = manager.run(_current_url(browser), timeout=30.0)
            validate_url(final_url, ctx.allow_local_browser)
        except Exception:
            final_url = ""
        return {
            "result": (history.final_result() or "")[:8000],
            "success": history.is_successful(),
            "steps": history.number_of_steps(),
            "url": final_url,
            "screenshots": [i["markdown"] for i in images],
        }

    return [
        Tool(
            name="browser_task",
            description=(
                "Give a browser agent a goal to accomplish on the web (navigate, "
                "click, fill forms, extract). Use for multi-step web work; use "
                "web_fetch instead for reading a single static page. Returns the "
                "agent's final answer and screenshots."
            ),
            parameters=schema(
                {
                    "task": {"type": "string", "description": "the goal, be specific"},
                    "url": {"type": "string", "description": "optional starting URL"},
                    "max_steps": {"type": "integer", "description": "step limit (default 25)"},
                    "vision": {
                        "type": "boolean",
                        "description": "send screenshots to the browser model (default true)",
                    },
                },
                ["task"],
            ),
            handler=task_handler,
            group="browser",
            effect="write",
            delegable=False,
        ),
        Tool(
            name="browser_open",
            description="Open a URL in the persistent browser session for this chat.",
            parameters=schema({"url": {"type": "string"}}, ["url"]),
            handler=open_handler,
            group="browser",
            delegable=False,
        ),
        Tool(
            name="browser_screenshot",
            description=(
                "Screenshot the current page and save it in the workspace; the "
                "owner sees the image. When an image-reader agent is assigned, "
                "the screenshot is described in text for you automatically; use "
                "question to focus the description."
            ),
            parameters=schema(
                {
                    "question": {
                        "type": "string",
                        "description": "what to ask about the screenshot",
                    },
                    "describe": {
                        "type": "boolean",
                        "description": "force (true) or skip (false) the description",
                    },
                },
                [],
            ),
            handler=screenshot_handler,
            group="browser",
            delegable=False,
        ),
        Tool(
            name="browser_get_content",
            description="Read the visible text of the current page or a CSS selector.",
            parameters=schema({"selector": {"type": "string"}}, []),
            handler=content_handler,
            group="browser",
            delegable=False,
        ),
        Tool(
            name="browser_click",
            description="Click an element by CSS selector or by its visible text.",
            parameters=schema(
                {
                    "selector": {"type": "string"},
                    "text": {"type": "string", "description": "visible text to click"},
                },
                [],
            ),
            handler=click_handler,
            group="browser",
            effect="write",
            delegable=False,
        ),
        Tool(
            name="browser_type",
            description="Fill an input matched by CSS selector.",
            parameters=schema(
                {"selector": {"type": "string"}, "text": {"type": "string"}},
                ["selector", "text"],
            ),
            handler=type_handler,
            group="browser",
            effect="write",
            delegable=False,
        ),
        Tool(
            name="browser_eval",
            description=(
                "Run JavaScript in the page and return the result. Pass an "
                "expression like document.title, or a function like "
                "() => { return document.body.innerText; }. Use it for inspecting "
                "DOM, computed styles, and app state during UI debugging."
            ),
            parameters=schema({"script": {"type": "string"}}, ["script"]),
            handler=eval_handler,
            group="browser",
            effect="write",
            delegable=False,
        ),
        Tool(
            name="browser_close",
            description="Close the browser session for this chat (frees memory).",
            parameters=schema({}, []),
            handler=close_handler,
            group="browser",
            effect="write",
            delegable=False,
        ),
    ]
