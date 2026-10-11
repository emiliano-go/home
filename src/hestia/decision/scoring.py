"""Pure decision scoring: values, pooling, veto, calibration, feedback.

Direct port of encoder's `session/decision.ts` scoring section so the composite,
verdict, and feedback text match across the two apps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from hestia.decision.calibration import Calibration, calibrate_value
from hestia.decision.config import Settings

WEIGHTS: dict[str, float] = {
    "requirements_met": 0.4,
    "no_unrelated_changes": 0.25,
    "bug_risk": 0.25,
    "unsafe_patterns": 0.1,
    "answer_quality": 0.4,
}
BUG_RISK_MAX = 3
ANSWER_QUALITY_MAX = 3

Verdict = str  # "pass" | "fail" | "needs_review"


@dataclass(frozen=True)
class Failure:
    key: str
    instructions: str
    observed: float | None
    confidence: float | None


@dataclass(frozen=True)
class DecisionResult:
    verdict: Verdict
    composite: float | None
    vetoes: list[str]
    failures: list[Failure]
    calibration_version: str | None


def value_of(key: str, answer: dict) -> float | None:
    if key == "bug_risk":
        score = answer.get("score")
        if score is None:
            return None
        return 1 - min(max(float(score), 0.0), BUG_RISK_MAX) / BUG_RISK_MAX
    if key == "answer_quality":
        score = answer.get("score")
        if score is None:
            return None
        return min(max(float(score), 0.0), ANSWER_QUALITY_MAX) / ANSWER_QUALITY_MAX
    noul = answer.get("noul")
    if noul is None:
        return None
    if key == "unsafe_patterns":
        return 1 - float(noul)
    return float(noul)


def collect_values(answers: dict[str, dict]) -> list[tuple[str, float, float]]:
    entries: list[tuple[str, float, float]] = []
    for key, weight in WEIGHTS.items():
        answer = answers.get(key)
        if not answer:
            continue
        value = value_of(key, answer)
        if value is not None:
            entries.append((key, value, weight))
    return entries


def aggregate(entries: list[tuple[str, float, float]], mode: str) -> float | None:
    total = 0.0
    weight = 0.0
    for _, value, w in entries:
        if mode == "logodds":
            clamped = min(max(value, 1e-3), 1 - 1e-3)
            total += w * math.log(clamped / (1 - clamped))
        else:
            total += w * value
        weight += w
    if weight == 0:
        return None
    pooled = total / weight
    return 1 / (1 + math.exp(-pooled)) if mode == "logodds" else pooled


def composite(answers: dict[str, dict]) -> float | None:
    return aggregate(collect_values(answers), "weighted")


def verdict(answers: dict[str, dict], settings: Settings) -> tuple[Verdict, float | None]:
    score = composite(answers)
    uncertain = any(
        answer.get("confidence") is not None and answer["confidence"] < settings.confidence_floor
        for answer in answers.values()
    )
    if uncertain or score is None:
        return "needs_review", score
    return ("pass" if score >= settings.pass_threshold else "fail"), score


def failures(questions: dict[str, dict], answers: dict[str, dict]) -> list[Failure]:
    result: list[Failure] = []
    for key in WEIGHTS:
        answer = answers.get(key)
        question = questions.get(key)
        if not answer or not question:
            continue
        value = value_of(key, answer)
        if value is None or value >= 0.5:
            continue
        observed = answer.get("score", answer.get("noul"))
        result.append(Failure(key, question.get("instructions", ""), observed, answer.get("confidence")))
    return result


def decide(
    answers: dict[str, dict],
    questions: dict[str, dict],
    settings: Settings,
    calibration: Calibration | None = None,
) -> DecisionResult:
    entries = []
    for key, value, weight in collect_values(answers):
        calibrator = calibration.questions.get(key) if calibration else None
        entries.append((key, calibrate_value(calibrator, value), weight))
    score = aggregate(entries, settings.aggregation)
    vetoes = [key for key, value, _ in entries if value < settings.veto_threshold]
    failing = failures(questions, answers)
    version = calibration.version if calibration else None
    if vetoes:
        return DecisionResult("fail", score, vetoes, failing, version)
    floor = calibration.confidence_floor if calibration and calibration.confidence_floor is not None else settings.confidence_floor
    uncertain = any(
        answer.get("confidence") is not None and answer["confidence"] < floor for answer in answers.values()
    )
    if uncertain or score is None:
        return DecisionResult("needs_review", score, vetoes, failing, version)
    threshold = calibration.pass_threshold if calibration and calibration.pass_threshold is not None else settings.pass_threshold
    return DecisionResult("pass" if score >= threshold else "fail", score, vetoes, failing, version)


def _finding_lines(findings: list[dict] | None) -> list[str]:
    if not findings:
        return []
    return ["Deterministic checks flagged:", *(f"- {f.get('rule')}: {f.get('detail')}" for f in findings)]


def review_feedback(
    *,
    composite: float | None,
    threshold: float,
    failures: list[Failure],
    vetoes: list[str] | None = None,
    findings: list[dict] | None = None,
) -> str:
    score = "n/a" if composite is None else f"{composite:.2f}"
    lines = [
        f"- {failure.key}: {failure.instructions} (observed: {failure.observed if failure.observed is not None else 'n/a'}, confidence: {failure.confidence if failure.confidence is not None else 'n/a'})"
        for failure in failures
    ]
    parts = [
        f"Decision engine could not confidently pass your last changes (composite {score}, threshold {threshold}).",
        *([f"Vetoed criteria: {', '.join(vetoes)}."] if vetoes else []),
        *_finding_lines(findings),
        "Strengthen the evidence before finishing: run the relevant tests and linters, fix the flagged items, and report the results.",
        *lines,
    ]
    return "\n".join(parts)


def feedback(*, composite: float | None, threshold: float, failures: list[Failure], findings: list[dict] | None = None) -> str:
    score = "n/a" if composite is None else f"{composite:.2f}"
    lines = [
        f"- {failure.key}: {failure.instructions} (observed: {failure.observed if failure.observed is not None else 'n/a'}, confidence: {failure.confidence if failure.confidence is not None else 'n/a'})"
        for failure in failures
    ]
    return "\n".join(
        [
            f"Decision engine evaluation of your last changes failed (composite {score} < {threshold}).",
            *_finding_lines(findings),
            "Address the following issues before finishing:",
            *lines,
            "Make the minimal changes needed to resolve them, then stop.",
        ]
    )
