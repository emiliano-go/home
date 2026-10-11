"""Decision-engine configuration.

Mirrors encoder's `decision` config section so the same config keys and state
file work: a `decision` dict (from hestia settings or an encoder.json section),
merged over defaults, with `DECISION_BASE_URL` / `DECISION_API_KEY` env
fallbacks. The encoder-managed state file (`~/.config/encoder/decision.json`) is
merged last so it wins, matching encoder's behavior.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

Aggregation = Literal["weighted", "logodds"]
ReviewAction = Literal["deny", "feedback", "ignore"]
ExternalMode = Literal["auto", "on", "off"]


@dataclass(frozen=True)
class VerifySettings:
    enabled: bool = True
    external: ExternalMode = "auto"
    disable: tuple[str, ...] = ()
    command: str | None = None


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None
    max_feedback_retries: int = 2
    pass_threshold: float = 0.8
    confidence_floor: float = 0.7
    question_file: str | None = None
    api_key: str | None = None
    help: bool = True
    capture_state: bool = False
    calibration_file: str | None = None
    veto_threshold: float = 0.5
    aggregation: Aggregation = "weighted"
    review_action: ReviewAction = "deny"
    verify: VerifySettings = field(default_factory=VerifySettings)


def defaults() -> Settings:
    return Settings()


def _number(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _flag(value: Any, fallback: bool) -> bool:
    return bool(value) if isinstance(value, bool) else fallback


def resolve(section: Any) -> Settings:
    """Apply a raw `decision` section dict over the defaults."""
    base = defaults()
    if not isinstance(section, dict):
        return base
    verify_raw = section.get("verify")
    verify_raw = verify_raw if isinstance(verify_raw, dict) else {}
    verify = VerifySettings(
        enabled=_flag(verify_raw.get("enabled"), base.verify.enabled),
        external=verify_raw.get("external") if verify_raw.get("external") in ("auto", "on", "off") else base.verify.external,
        disable=tuple(verify_raw["disable"]) if isinstance(verify_raw.get("disable"), list) else base.verify.disable,
        command=verify_raw.get("command") if isinstance(verify_raw.get("command"), str) else base.verify.command,
    )
    return replace(
        base,
        enabled=_flag(section.get("enabled"), base.enabled),
        base_url=section.get("baseUrl") if isinstance(section.get("baseUrl"), str) else base.base_url,
        model=section.get("model") if isinstance(section.get("model"), str) else base.model,
        max_feedback_retries=int(section["maxFeedbackRetries"]) if isinstance(section.get("maxFeedbackRetries"), int) else base.max_feedback_retries,
        pass_threshold=_number(section.get("passThreshold"), base.pass_threshold),
        confidence_floor=_number(section.get("confidenceFloor"), base.confidence_floor),
        question_file=section.get("questionFile") if isinstance(section.get("questionFile"), str) else base.question_file,
        api_key=section.get("apiKey") if isinstance(section.get("apiKey"), str) else base.api_key,
        help=_flag(section.get("help"), base.help),
        capture_state=_flag(section.get("captureState"), base.capture_state),
        calibration_file=section.get("calibrationFile") if isinstance(section.get("calibrationFile"), str) else base.calibration_file,
        veto_threshold=_number(section.get("vetoThreshold"), base.veto_threshold),
        aggregation=section.get("aggregation") if section.get("aggregation") in ("weighted", "logodds") else base.aggregation,
        review_action=section.get("reviewAction") if section.get("reviewAction") in ("deny", "feedback", "ignore") else base.review_action,
        verify=verify,
    )


def effective_base_url(settings: Settings) -> str | None:
    return settings.base_url or os.environ.get("DECISION_BASE_URL")


def effective_api_key(settings: Settings) -> str | None:
    return settings.api_key or os.environ.get("DECISION_API_KEY")


def state_file() -> Path:
    """Encoder-compatible managed state file; `HESTIA_DECISION_STATE` overrides."""
    override = os.environ.get("HESTIA_DECISION_STATE")
    if override:
        return Path(override)
    return Path.home() / ".config" / "encoder" / "decision.json"


def load_state(file: Path | None = None) -> dict:
    path = file or state_file()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def merge_state(state: dict, patch: Any) -> dict:
    if not isinstance(patch, dict):
        return state
    merged = dict(state)
    for key, value in patch.items():
        if key == "verify" and isinstance(value, dict) and isinstance(merged.get("verify"), dict):
            merged["verify"] = {**merged["verify"], **value}
        else:
            merged[key] = value
    return merged


def load_settings(section: Any = None) -> Settings:
    """Merge the managed state file last so it wins, then resolve."""
    return resolve({**(section or {}), **load_state()})
