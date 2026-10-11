"""Per-question calibration artifacts (Platt / isotonic), ported from encoder.

The runtime side: `calibrate_value` maps a raw criterion value through the
fitted calibrator; a missing or invalid artifact means uncalibrated scoring.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Calibrator:
    kind: str
    a: float = 0.0
    b: float = 0.0
    points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class Calibration:
    version: str
    created_at: float
    questions: dict[str, Calibrator]
    pass_threshold: float | None = None
    confidence_floor: float | None = None


def _parse_calibrator(raw: Any) -> Calibrator | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("kind") == "platt":
        return Calibrator("platt", a=float(raw.get("a", 0.0)), b=float(raw.get("b", 0.0)))
    if raw.get("kind") == "isotonic":
        points = raw.get("points")
        if not isinstance(points, list):
            return None
        parsed = tuple((float(pt[0]), float(pt[1])) for pt in points if isinstance(pt, (list, tuple)) and len(pt) == 2)
        return Calibrator("isotonic", points=parsed)
    return None


def calibrate_value(calibrator: Calibrator | None, value: float) -> float:
    if calibrator is None:
        return value
    if calibrator.kind == "platt":
        mapped = 1 / (1 + math.exp(-(calibrator.a * value + calibrator.b)))
        return min(max(mapped, 0.0), 1.0)
    points = calibrator.points
    if not points:
        return value
    first_x, first_y = points[0]
    if value <= first_x:
        return first_y
    last_x, last_y = points[-1]
    if value >= last_x:
        return last_y
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        if value <= x1:
            t = 0.0 if x1 == x0 else (value - x0) / (x1 - x0)
            return y0 + (y1 - y0) * t
    return value


def parse_calibration(raw: Any) -> Calibration | None:
    if not isinstance(raw, dict):
        return None
    questions_raw = raw.get("questions")
    if not isinstance(questions_raw, dict):
        return None
    questions = {key: cal for key, value in questions_raw.items() if (cal := _parse_calibrator(value)) is not None}
    return Calibration(
        version=str(raw.get("version", "")),
        created_at=float(raw.get("createdAt", 0.0)),
        questions=questions,
        pass_threshold=raw.get("passThreshold") if isinstance(raw.get("passThreshold"), (int, float)) else None,
        confidence_floor=raw.get("confidenceFloor") if isinstance(raw.get("confidenceFloor"), (int, float)) else None,
    )


def load_calibration(path: str | None) -> Calibration | None:
    if not path:
        return None
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return parse_calibration(raw)
