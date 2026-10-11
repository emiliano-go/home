"""Decision-engine service: evaluate a completed agent turn.

Ported from encoder's `SessionDecision.evaluate`. Order: memory context →
deterministic verify lane (a high finding vetoes without calling the engine) →
build+normalize state → POST to Laya → decide → log → rate the turn's memories.
Every step is best-effort; evaluation never breaks the agent loop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hestia import totem_store
from hestia.decision import config, questions as questions_mod, state as state_mod, verify
from hestia.decision.calibration import load_calibration
from hestia.decision.client import ask
from hestia.decision.scoring import DecisionResult, Failure, decide

LOG_DIR = ".encoder"
LOG_FILE = "decision-log.jsonl"
STATE_FILE = "decision-states.jsonl"


@dataclass
class EvaluateInput:
    task: str
    assistant_text: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    mutations: list[dict] = field(default_factory=list)
    grounding: list[dict] = field(default_factory=list)
    session_id: str = ""
    message_id: str = ""
    project_dir: Path | None = None
    cwd: str | None = None


@dataclass
class Evaluation:
    kind: str
    verdict: str
    composite: float | None
    vetoes: list[str]
    failures: list[Failure]
    findings: list[dict]
    answers: dict
    usage: dict | None
    calibration_version: str | None


def _log_path(project_dir: Path) -> Path:
    return project_dir / LOG_DIR / LOG_FILE


def _capture_path(project_dir: Path) -> Path:
    return project_dir / LOG_DIR / STATE_FILE


def select_memory(project_dir: Path | None, task: str, limit: int = 2) -> list[dict]:
    """Ranked project memory for the judge, shaped like encoder's DecisionMemory."""
    if project_dir is None:
        return []
    try:
        hits = totem_store.search(project_dir, task, limit=10)
    except Exception:
        return []
    words = {w for w in __import__("re").findall(r"[a-z0-9_]+", (task or "").lower()) if len(w) > 3}
    ranked = sorted(
        hits,
        key=lambda item: len(words & {w for w in __import__("re").findall(r"[a-z0-9_]+", f"{item.get('title', '')} {item.get('statement', '')}".lower())}),
        reverse=True,
    )
    return [
        {"id": item.get("id"), "type": item.get("type"), "title": item.get("title") or "", "statement": item.get("statement") or ""}
        for item in ranked[:limit]
    ]


def rate_memories(project_dir: Path | None, ids: list[str], rating: dict) -> None:
    if project_dir is None or not ids:
        return
    for memory_id in ids:
        try:
            totem_store.update(project_dir, memory_id, metadata={"decision": rating})
        except Exception:
            continue


class DecisionService:
    def settings(self) -> config.Settings:
        return config.load_settings()

    async def query(self, state: dict, question_set: dict) -> dict | None:
        settings = self.settings()
        base_url = config.effective_base_url(settings)
        if not base_url:
            return None
        return await ask(base_url, state, question_set, model=settings.model, api_key=config.effective_api_key(settings))

    async def evaluate(self, turn: EvaluateInput) -> Evaluation | None:
        settings = self.settings()
        base_url = config.effective_base_url(settings)
        if not settings.enabled or not base_url:
            return None

        kind = "mutation" if turn.mutations else "answer"
        override = questions_mod.load_questions(settings.question_file) if kind == "mutation" else None
        question_set = questions_mod.questions_for(kind, override)
        calibration = load_calibration(settings.calibration_file)

        memory_items = select_memory(turn.project_dir, turn.task, limit=2)

        findings: list[dict] = []
        if settings.verify.enabled:
            builtin, vetoed = verify.verify_changes(turn.mutations, settings.verify.disable)
            findings += builtin
            paths = [path for mutation in turn.mutations for path in (mutation.get("paths") or [])]
            if not vetoed and paths and settings.verify.external != "off":
                findings += verify.verify_external_files(paths, cwd=turn.cwd, mode=settings.verify.external, disable=settings.verify.disable)
            if not vetoed and settings.verify.command and turn.mutations and turn.cwd:
                command_findings, _ = verify.run_verify_command(settings.verify.command, turn.cwd)
                findings += command_findings
        veto = any(finding.get("severity") == "high" for finding in findings)

        engine_state = state_mod.normalize_state(
            state_mod.build_state(
                task=turn.task,
                assistant_text=turn.assistant_text,
                tool_calls=turn.tool_calls,
                mutations=turn.mutations,
                grounding=turn.grounding,
                memory=memory_items,
            )
        )
        response = None if veto else await ask(base_url, engine_state, question_set, model=settings.model, api_key=config.effective_api_key(settings))
        if response is None and not veto:
            return None

        if response is not None:
            decided = decide(response.get("answers", {}), question_set, settings, calibration)
            answers = response.get("answers", {})
            usage = response.get("usage")
        else:
            decided = DecisionResult("fail", None, [], [], None)
            answers, usage = {}, None
        if veto:
            decided = DecisionResult("fail", decided.composite, decided.vetoes, decided.failures, decided.calibration_version)

        outcome = Evaluation(
            kind=kind,
            verdict=decided.verdict,
            composite=decided.composite,
            vetoes=decided.vetoes,
            failures=decided.failures,
            findings=findings,
            answers=answers,
            usage=usage,
            calibration_version=decided.calibration_version,
        )
        self._append_log(turn, outcome)
        if settings.capture_state and turn.project_dir is not None:
            self._capture_state(turn, engine_state, question_set)
        rate_memories(
            turn.project_dir,
            [item["id"] for item in memory_items if item.get("id")],
            {"composite": outcome.composite, "verdict": outcome.verdict, "kind": kind, "sessionID": turn.session_id, "messageID": turn.message_id, "time": int(time.time() * 1000)},
        )
        return outcome

    def evaluations(self, project_dir: Path, limit: int = 50) -> list[dict]:
        path = _log_path(project_dir)
        try:
            lines = [line for line in path.read_text().splitlines() if line.strip()]
        except OSError:
            return []
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries

    def _append_log(self, turn: EvaluateInput, outcome: Evaluation) -> None:
        if turn.project_dir is None:
            return
        path = _log_path(turn.project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": int(time.time() * 1000),
            "kind": outcome.kind,
            "sessionID": turn.session_id,
            "messageID": turn.message_id,
            "composite": outcome.composite,
            "verdict": outcome.verdict,
            "vetoes": outcome.vetoes,
            "verify": outcome.findings,
            "answers": outcome.answers,
            "usage": outcome.usage,
            "calibrationVersion": outcome.calibration_version,
        }
        try:
            with path.open("a") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            return

    def _capture_state(self, turn: EvaluateInput, engine_state: dict, question_set: dict) -> None:
        path = _capture_path(turn.project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a") as handle:
                handle.write(json.dumps({"state": engine_state, "questions": question_set, "time": int(time.time() * 1000)}) + "\n")
        except OSError:
            return
