"""Built-in decision question sets, ported from encoder.

Same ids, instructions, types (noul/choice/score) and criteria so captured
states, question-file overrides, and the Laya wire format stay compatible.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_QUESTIONS: dict[str, dict] = {
    "requirements_met": {
        "type": "noul",
        "instructions": "The code changes fully satisfy the user's request described in the task.",
    },
    "no_unrelated_changes": {
        "type": "noul",
        "instructions": "The code changes contain no modifications unrelated to the user's request.",
    },
    "bug_risk": {
        "type": "score",
        "instructions": "Rate the risk that the code changes introduce bugs.",
        "criteria": [
            "No risk: changes are trivially correct",
            "Low risk: minor logic changes, easily verified",
            "Medium risk: non-trivial logic with plausible edge-case bugs",
            "High risk: likely broken or clearly incorrect logic",
        ],
    },
    "change_type": {
        "type": "choice",
        "instructions": "What kind of change did the assistant make?",
        "criteria": {
            "minimal-fix": "The smallest change that addresses the request",
            "refactor": "Restructures existing code beyond the immediate request",
            "rewrite": "Rewrites or replaces large portions of existing code",
        },
    },
}

DEFAULT_QUESTIONS_NO_MUTATION: dict[str, dict] = {
    "requirements_met": DEFAULT_QUESTIONS["requirements_met"],
    "bug_risk": DEFAULT_QUESTIONS["bug_risk"],
    "answer_quality": {
        "type": "score",
        "instructions": "Rate how completely and correctly the assistant's answer addresses the user's request.",
        "criteria": [
            "Wrong or missing: the answer does not address the request or is incorrect",
            "Partial: the answer addresses the request but omits important parts",
            "Mostly complete: addresses the request with only minor omissions",
            "Complete: fully and correctly addresses the request",
        ],
    },
}


def load_questions(path: str | None) -> dict[str, dict]:
    """Load a question-file override; absent/invalid falls back to the defaults."""
    if not path:
        return DEFAULT_QUESTIONS
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return DEFAULT_QUESTIONS
    if not isinstance(raw, dict):
        return DEFAULT_QUESTIONS
    return {key: value for key, value in raw.items() if isinstance(value, dict)} or DEFAULT_QUESTIONS


def questions_for(kind: str, override: dict[str, dict] | None = None) -> dict[str, dict]:
    if kind == "mutation":
        return override or DEFAULT_QUESTIONS
    return DEFAULT_QUESTIONS_NO_MUTATION
