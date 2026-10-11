"""Decision-engine HTTP surface: config snapshot, evaluations log, config patch."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from hestia import repos
from hestia.decision import config
from hestia.decision.service import DecisionService
from hestia.registry.db import session as db_session
from hestia.registry.models import Project

router = APIRouter(prefix="/api", tags=["decision"])
_service = DecisionService()


def _snapshot() -> dict:
    settings = _service.settings()
    return {
        "enabled": settings.enabled,
        "hasBaseUrl": config.effective_base_url(settings) is not None,
        "hasKey": config.effective_api_key(settings) is not None,
        "stateFile": str(config.state_file()),
        "settings": {
            "baseUrl": settings.base_url,
            "model": settings.model,
            "maxFeedbackRetries": settings.max_feedback_retries,
            "passThreshold": settings.pass_threshold,
            "confidenceFloor": settings.confidence_floor,
            "vetoThreshold": settings.veto_threshold,
            "aggregation": settings.aggregation,
            "reviewAction": settings.review_action,
            "captureState": settings.capture_state,
            "verify": {
                "enabled": settings.verify.enabled,
                "external": settings.verify.external,
                "command": settings.verify.command,
                "disable": list(settings.verify.disable),
            },
        },
    }


@router.get("/decision")
def get_decision():
    return _snapshot()


@router.patch("/decision")
def patch_decision(patch: dict = Body(...)):
    merged = config.merge_state(config.load_state(), patch)
    try:
        path = config.state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__import__("json").dumps(merged, indent=2) + "\n")
    except OSError as error:
        raise HTTPException(500, f"could not write decision state: {error}") from error
    return _snapshot()


@router.get("/projects/{project_id}/decision/evaluations")
def project_evaluations(project_id: int, limit: int = 50, s: Session = Depends(db_session)):
    project = s.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    rows = repos.repos_for(s, project_id)
    root = Path(rows[0].local_path) if rows and rows[0].local_path else repos.memory_root(project)
    return _service.evaluations(root, limit=limit)
