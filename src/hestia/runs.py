"""Run registry: every agent execution with a resumable event stream.

A run is created for each chat turn, subagent, memory writer, or one-off
agent execution. Events are numbered (``seq``) and buffered so a client whose
network dropped can re-attach with ``Last-Event-ID`` and replay what it
missed. Runs keep going when the client disconnects; only an explicit stop
(or the wall-clock guard) ends them early.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

TERMINAL = ("done", "error", "stopped", "timed_out")
MAX_EVENTS = 2000
HEARTBEAT_SECONDS = float(os.environ.get("HESTIA_SSE_HEARTBEAT", "15"))
MAX_RUNS = 200  # registry size; oldest finished runs are dropped


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@dataclass
class Run:
    id: str
    kind: str  # chat | subagent | memory-writer
    project_id: int | None = None
    session_id: str | None = None
    parent_run_id: str | None = None
    title: str = ""
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    steps: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    subscribers: list[tuple[Any, asyncio.Queue]] = field(default_factory=list)
    seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def last_event(self) -> dict | None:
        return self.events[-1] if self.events else None


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(
        self,
        kind: str,
        *,
        project_id: int | None = None,
        session_id: str | None = None,
        parent_run_id: str | None = None,
        title: str = "",
    ) -> Run:
        run = Run(
            id=str(uuid.uuid4()),
            kind=kind,
            project_id=project_id,
            session_id=session_id,
            parent_run_id=parent_run_id,
            title=title[:120],
        )
        with self._lock:
            self._runs[run.id] = run
            self._reap_locked()
        return run

    def _reap_locked(self) -> None:
        if len(self._runs) <= MAX_RUNS:
            return
        finished = sorted(
            (r for r in self._runs.values() if r.status in TERMINAL),
            key=lambda r: r.finished_at or r.created_at,
        )
        for run in finished[: len(self._runs) - MAX_RUNS]:
            self._runs.pop(run.id, None)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def emit(self, run: Run, event: dict[str, Any]) -> dict[str, Any]:
        """Append an event (any thread) and fan it out to subscribers."""
        with run.lock:
            run.seq += 1
            ev = {**event, "seq": run.seq, "run_id": run.id, "ts": time.time()}
            run.events.append(ev)
            if event.get("type") == "usage":
                for key, value in (event.get("usage") or {}).items():
                    if isinstance(value, (int, float)):
                        run.tokens[key] = run.tokens.get(key, 0) + int(value)
            subs = list(run.subscribers)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, ev)
            except RuntimeError:
                pass
        return ev

    async def subscribe(self, run: Run, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay events after ``after``, then tail until the run ends."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        with run.lock:
            replay = [e for e in run.events if e["seq"] > after]
            done = run.status in TERMINAL
            if not done:
                run.subscribers.append((loop, queue))
        for ev in replay:
            yield ev
        if done:
            return
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield {"type": "ping", "seq": run.seq, "run_id": run.id}
                    continue
                if ev is None:
                    return
                yield ev
        finally:
            with run.lock:
                run.subscribers = [s for s in run.subscribers if s[1] is not queue]

    def finish(
        self, run: Run, status: str = "done", result: str = "", error: str = ""
    ) -> None:
        with run.lock:
            if run.status in TERMINAL:
                return
            run.status = status
            run.finished_at = time.time()
            run.result = (result or "")[:20_000]
            run.error = (error or "")[:2000]
            subs = list(run.subscribers)
        event_type = status if status in TERMINAL else "done"
        self.emit(run, {"type": event_type, "result": run.result, "error": run.error})
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except RuntimeError:
                pass

    def stop(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None or run.status in TERMINAL:
            return False
        run.cancel.set()
        return True

    def active(self, project_id: int | None = None) -> list[Run]:
        with self._lock:
            runs = [r for r in self._runs.values() if r.status not in TERMINAL]
        if project_id is not None:
            runs = [r for r in runs if r.project_id == project_id]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def recent(self, limit: int = 100) -> list[Run]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def as_dict(self, run: Run) -> dict[str, Any]:
        return {
            "id": run.id,
            "kind": run.kind,
            "parent_run_id": run.parent_run_id,
            "project_id": run.project_id,
            "session_id": run.session_id,
            "title": run.title,
            "status": run.status,
            "created_at": _iso(run.created_at),
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "elapsed": round(
                (run.finished_at or time.time()) - run.started_at, 1
            ),
            "steps": run.steps,
            "tokens": run.tokens,
            "result": run.result,
            "error": run.error,
            "last_event": run.last_event(),
        }


manager = RunManager()
