"""Plan limits and usage metering."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import AuthContext
from app.database import AnswerLibraryItem, KnowledgeDoc, Questionnaire, UsageEvent


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def count_questionnaires_this_month(db: Session, workspace_id: int) -> int:
    start = _month_start()
    return (
        db.query(UsageEvent)
        .filter(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.event_type == "questionnaire_upload",
            UsageEvent.created_at >= start,
        )
        .count()
    )


def record_questionnaire_upload(db: Session, workspace_id: int) -> None:
    db.add(
        UsageEvent(
            workspace_id=workspace_id,
            event_type="questionnaire_upload",
        )
    )
    db.commit()


def assert_can_upload_doc(db: Session, auth: AuthContext) -> None:
    n = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.workspace_id == auth.workspace.id)
        .count()
    )
    if n >= auth.limits["max_docs"]:
        raise HTTPException(
            402,
            f"Free plan limit: max {auth.limits['max_docs']} knowledge docs. Upgrade to Pro.",
        )


def assert_can_upload_questionnaire(
    db: Session, auth: AuthContext, question_count: int
) -> None:
    if question_count > auth.limits["max_questions_per_qn"]:
        raise HTTPException(
            402,
            f"Plan limit: max {auth.limits['max_questions_per_qn']} questions per questionnaire.",
        )
    used = count_questionnaires_this_month(db, auth.workspace.id)
    if used >= auth.limits["max_questionnaires_per_month"]:
        raise HTTPException(
            402,
            f"Plan limit: {auth.limits['max_questionnaires_per_month']} questionnaires/month. Upgrade to Pro.",
        )


def assert_can_save_library(db: Session, auth: AuthContext) -> None:
    n = (
        db.query(AnswerLibraryItem)
        .filter(AnswerLibraryItem.workspace_id == auth.workspace.id)
        .count()
    )
    if n >= auth.limits["max_answer_library"]:
        raise HTTPException(
            402,
            f"Plan limit: max {auth.limits['max_answer_library']} library answers.",
        )


def usage_snapshot(db: Session, auth: AuthContext) -> dict:
    ws = auth.workspace.id
    return {
        "plan": auth.plan,
        "limits": auth.limits,
        "usage": {
            "docs": db.query(KnowledgeDoc).filter(KnowledgeDoc.workspace_id == ws).count(),
            "questionnaires_this_month": count_questionnaires_this_month(db, ws),
            "questionnaires_total": db.query(Questionnaire)
            .filter(Questionnaire.workspace_id == ws)
            .count(),
            "library_items": db.query(AnswerLibraryItem)
            .filter(AnswerLibraryItem.workspace_id == ws)
            .count(),
        },
    }
