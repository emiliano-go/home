"""FastAPI app factory: API routers + built frontend."""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hestia import __version__, auth, jobs, scheduler
from hestia.registry.db import init_db
from hestia.routers import (
    activity,
    agents,
    auth as auth_router,
    capture,
    chat,
    decision,
    docs,
    github,
    goals,
    implement,
    inbox,
    jobs as jobs_router,
    milestones,
    notify as notify_router,
    overview,
    projects,
    providers,
    reminders,
    runs,
    schedules,
    search,
    sessions,
    settings as settings_router,
    skills,
    tasks,
    triage,
    watches,
    workspace,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.manager.start()
    task = None
    if os.environ.get("HESTIA_DISABLE_SCHEDULER") != "1":
        task = asyncio.create_task(scheduler.worker())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        from hestia.tools import browser as browser_tools

        await asyncio.to_thread(browser_tools.manager.shutdown)


def create_app() -> FastAPI:
    app = FastAPI(title="hestia", version=__version__, lifespan=lifespan)
    init_db()

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        path = request.url.path
        if (
            auth.enabled()
            and path.startswith("/api/")
            and not path.startswith("/api/auth/")
            and not auth.verify_session(request.cookies.get(auth.SESSION_COOKIE))
        ):
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        return await call_next(request)

    app.include_router(activity.router)
    app.include_router(overview.router)
    app.include_router(tasks.router)
    app.include_router(milestones.router)
    app.include_router(goals.router)
    app.include_router(triage.router)
    app.include_router(docs.router)
    app.include_router(projects.router)
    app.include_router(chat.router)
    app.include_router(capture.router)
    app.include_router(implement.router)
    app.include_router(jobs_router.router)
    app.include_router(runs.router)
    app.include_router(providers.router)
    app.include_router(sessions.router)
    app.include_router(agents.router)
    app.include_router(agents.actions_router)
    app.include_router(workspace.router)
    app.include_router(search.router)
    app.include_router(inbox.router)
    app.include_router(schedules.router)
    app.include_router(reminders.router)
    app.include_router(watches.router)
    app.include_router(auth_router.router)
    app.include_router(notify_router.router)
    app.include_router(settings_router.router)
    app.include_router(github.router)
    app.include_router(skills.router)
    app.include_router(decision.router)

    dist = find_web_dist()
    if dist:
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def find_web_dist() -> Path | None:
    """Locate the built SPA: env override, repo checkout, or Docker layout."""
    import os

    candidates = [
        os.environ.get("WEB_DIST"),
        Path.cwd() / "web" / "dist",
        Path(__file__).parents[2] / "web" / "dist",  # editable/src install
        Path("/app/web/dist"),  # Docker image layout
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


app = create_app()
