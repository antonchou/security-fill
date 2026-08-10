"""Reusable answer library: save reviewed answers, match on new questionnaires."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import AnswerLibraryItem
from app.services.llm import keyword_overlap_score


def normalize_question(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\u4e00-\u9fff\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Cap length for unique constraint key
    return t[:480]


def upsert_library_answer(
    db: Session,
    workspace_id: int,
    question_text: str,
    answer_text: str,
    section: str = "",
) -> AnswerLibraryItem:
    if not answer_text or not answer_text.strip():
        raise ValueError("Empty answer cannot be saved to library")
    qnorm = normalize_question(question_text)
    item = (
        db.query(AnswerLibraryItem)
        .filter(
            AnswerLibraryItem.workspace_id == workspace_id,
            AnswerLibraryItem.question_norm == qnorm,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if item:
        item.answer_text = answer_text.strip()
        item.question_text = question_text
        item.section = section or item.section
        item.updated_at = now
    else:
        item = AnswerLibraryItem(
            workspace_id=workspace_id,
            question_norm=qnorm,
            question_text=question_text,
            answer_text=answer_text.strip(),
            section=section or "",
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_library(db: Session, workspace_id: int) -> list[AnswerLibraryItem]:
    return (
        db.query(AnswerLibraryItem)
        .filter(AnswerLibraryItem.workspace_id == workspace_id)
        .order_by(AnswerLibraryItem.updated_at.desc())
        .all()
    )


def delete_library_item(db: Session, workspace_id: int, item_id: int) -> bool:
    item = db.get(AnswerLibraryItem, item_id)
    if not item or item.workspace_id != workspace_id:
        return False
    db.delete(item)
    db.commit()
    return True


def find_library_match(
    db: Session,
    workspace_id: int,
    question_text: str,
    *,
    exact_threshold: float = 0.92,
    fuzzy_threshold: float = 0.55,
) -> AnswerLibraryItem | None:
    """Exact norm match first, then best fuzzy keyword match."""
    qnorm = normalize_question(question_text)
    exact = (
        db.query(AnswerLibraryItem)
        .filter(
            AnswerLibraryItem.workspace_id == workspace_id,
            AnswerLibraryItem.question_norm == qnorm,
        )
        .first()
    )
    if exact:
        return exact

    items = (
        db.query(AnswerLibraryItem)
        .filter(AnswerLibraryItem.workspace_id == workspace_id)
        .all()
    )
    if not items:
        return None

    best: AnswerLibraryItem | None = None
    best_score = 0.0
    for it in items:
        score = keyword_overlap_score(question_text, it.question_text)
        # boost if one contains the other
        a, b = qnorm, it.question_norm
        if a and b and (a in b or b in a):
            score = max(score, 0.7)
        if score > best_score:
            best_score = score
            best = it
    if best and best_score >= fuzzy_threshold:
        return best
    return None


def mark_library_used(db: Session, item: AnswerLibraryItem) -> None:
    item.times_used = (item.times_used or 0) + 1
    db.add(item)
    db.commit()
