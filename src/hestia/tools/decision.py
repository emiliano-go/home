"""`decision_ask`: let the agent consult the decision judge mid-turn.

Forwards a minimal state (task required; answer/changes/memory optional) plus a
question set to the Laya judge and returns its typed answers, verdict, and
composite. Read-only; no-op (``answered: false``) when the engine is disabled.
"""

from __future__ import annotations

from hestia.decision import config as decision_config
from hestia.decision import questions as questions_mod
from hestia.decision.client import ask_sync
from hestia.decision.scoring import decide
from hestia.tools.registry import ProjectContext, Registry, Tool, schema


def _ask(ctx: ProjectContext, args: dict) -> dict:
    settings = decision_config.load_settings()
    base_url = decision_config.effective_base_url(settings)
    if not settings.enabled or not base_url:
        return {"answered": False, "reason": "decision engine is disabled"}
    state = args.get("state")
    if not isinstance(state, dict) or not state.get("task"):
        raise ValueError("state.task is required")
    question_set = args.get("questions") if isinstance(args.get("questions"), dict) else questions_mod.DEFAULT_QUESTIONS
    response = ask_sync(
        base_url,
        state,
        question_set,
        model=settings.model,
        api_key=decision_config.effective_api_key(settings),
    )
    if response is None:
        return {"answered": False, "reason": "decision engine unreachable"}
    result = decide(response.get("answers", {}), question_set, settings)
    return {
        "answered": True,
        "answers": response.get("answers", {}),
        "usage": response.get("usage"),
        "verdict": result.verdict,
        "composite": result.composite,
    }


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="decision_ask",
        description=(
            "Ask the decision judge whether a change satisfies the task. Provide "
            "state={'task': ..., 'answer'/'changes'/'memory' optional} and "
            "questions (defaults to the built-in set)."
        ),
        parameters=schema({
            "state": {"type": "object", "description": "strict decision state; task is required"},
            "questions": {"type": "object", "description": "question set keyed by question id"},
        }, ["state"]),
        handler=_ask,
        group="decision",
    ))
