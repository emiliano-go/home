"""Agent questions: persisted per chat session, answered by the next message.

The agent's ``ask_user`` tool records a question and ends the turn; the owner
answers by sending their next chat message (which marks every open question in
that session answered), so questions survive reloads and restarts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from hestia.registry.models import Question

STATUSES = ["open", "answered", "dismissed"]


class InvalidQuestion(ValueError):
    """Raised for invalid question input; mapped to HTTP 400 / tool errors."""


def parse_options(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:6]


def _parse_meta(value) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def as_dict(question: Question) -> dict:
    return {
        "id": question.id,
        "session_id": question.session_id,
        "project_id": question.project_id,
        "question": question.question,
        "kind": question.kind or "question",
        "meta": _parse_meta(question.meta),
        "options": parse_options(question.options),
        "status": question.status,
        "answer": question.answer,
        "created_at": question.created_at.isoformat() if question.created_at else None,
        "answered_at": question.answered_at.isoformat() if question.answered_at else None,
    }


def create(
    db: Session,
    session_id: str,
    project_id: int,
    question: str,
    options: list[str] | None = None,
    kind: str = "question",
    meta: dict | None = None,
) -> Question:
    question = (question or "").strip()
    if not question:
        raise InvalidQuestion("question is required")
    if kind not in ("question", "approval", "user_required"):
        raise InvalidQuestion("kind must be question, approval, or user_required")
    row = Question(
        session_id=session_id,
        project_id=project_id,
        question=question,
        kind=kind,
        meta=json.dumps(meta or {}),
        options=json.dumps(parse_options(options)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_for_session(db: Session, session_id: str) -> list[Question]:
    return db.exec(
        select(Question).where(Question.session_id == session_id).order_by(Question.id)
    ).all()


def open_for_session(db: Session, session_id: str) -> list[Question]:
    return db.exec(
        select(Question)
        .where(Question.session_id == session_id, Question.status == "open")
        .order_by(Question.id)
    ).all()


def answer(db: Session, question: Question, text: str) -> Question:
    question.status = "answered"
    question.answer = (text or "").strip() or None
    question.answered_at = datetime.now(timezone.utc)
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def dismiss(db: Session, question: Question) -> Question:
    question.status = "dismissed"
    question.answered_at = datetime.now(timezone.utc)
    db.add(question)
    db.commit()
    db.refresh(question)
    return question
