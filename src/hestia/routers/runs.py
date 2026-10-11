"""Runs API: list, stream (resumable), and stop agent executions."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from hestia import jobs, runs
from hestia.registry.db import session
from hestia.registry.models import BackgroundTask

router = APIRouter(prefix="/api", tags=["runs"])

_ACTIVE_JOBS = ("queued", "running")


def _job_run(job: BackgroundTask) -> dict:
    started = job.started_at
    finished = job.finished_at
    elapsed = 0.0
    if started is not None:
        end = finished or started
        if finished is not None:
            elapsed = (finished - started).total_seconds()
    return {
        "id": f"job-{job.id}",
        "kind": "background",
        "parent_run_id": None,
        "project_id": job.project_id,
        "session_id": job.session_id,
        "title": job.description or (job.instruction or "")[:80] or job.kind,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "elapsed": round(elapsed, 1),
        "steps": 0,
        "tokens": {},
        "result": (job.result or "")[:2000],
        "error": job.error or "",
        "last_event": None,
    }


@router.get("/runs")
def list_runs(
    project_id: int | None = None,
    active_only: bool = False,
    s: Session = Depends(session),
):
    entries = [
        runs.manager.as_dict(r)
        for r in (runs.manager.active(project_id) if active_only else runs.manager.recent())
    ]
    query = select(BackgroundTask)
    if project_id is not None:
        query = query.where(BackgroundTask.project_id == project_id)
    if active_only:
        query = query.where(BackgroundTask.status.in_(_ACTIVE_JOBS))
    for job in s.exec(query.order_by(BackgroundTask.id.desc()).limit(100)).all():
        entries.append(_job_run(job))
    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return entries


@router.get("/runs/{run_id}")
def get_run(run_id: str, s: Session = Depends(session)):
    run = runs.manager.get(run_id)
    if run is not None:
        return runs.manager.as_dict(run)
    if run_id.startswith("job-"):
        job = s.get(BackgroundTask, int(run_id[4:]))
        if job:
            return _job_run(job)
    raise HTTPException(404, "run not found")


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, after: int = 0):
    """SSE stream for a run; resumable via Last-Event-ID or ?after="""
    run = runs.manager.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    header = request.headers.get("last-event-id")
    start = int(header) if header and header.isdigit() else max(0, after)

    async def stream():
        async for event in runs.manager.subscribe(run, start):
            if event.get("type") == "ping":
                yield ": ping\n\n"
                continue
            payload = {k: v for k, v in event.items() if k != "type"}
            payload["event"] = event["type"]
            yield f"id: {event['seq']}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str):
    if run_id.startswith("job-"):
        job = jobs.stop(int(run_id[4:]))
        if job is None:
            raise HTTPException(404, "job not found")
        return {"stopped": job["status"] == "stopped", "run": job}
    run = runs.manager.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return {"stopped": runs.manager.stop(run_id)}
