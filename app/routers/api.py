from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import AuthDep
from app.config import UPLOAD_DIR
from app.database import Question, Questionnaire, get_db
from app.services import export_svc
from app.services.answer_engine import draft_all, draft_one
from app.services.answer_library import (
    delete_library_item,
    list_library,
    upsert_library_answer,
)
from app.services.knowledge import delete_doc, ingest_document, list_docs
from app.services.llm import has_llm
from app.services.plans import (
    assert_can_save_library,
    assert_can_upload_doc,
    assert_can_upload_questionnaire,
    record_questionnaire_upload,
    usage_snapshot,
)
from app.services.questionnaire import parse_questionnaire

router = APIRouter(prefix="/api")


class QuestionUpdate(BaseModel):
    answer_text: str | None = None
    status: str | None = None
    notes: str | None = None
    save_to_library: bool = False


class LibraryCreate(BaseModel):
    question_text: str
    answer_text: str
    section: str = ""


@router.get("/health")
def health():
    return {"ok": True, "service": "securityfill", "version": "1.0.0"}


@router.get("/status")
def status(auth: AuthDep, db: Session = Depends(get_db)):
    snap = usage_snapshot(db, auth)
    return {
        "llm_enabled": has_llm(),
        "plan": auth.plan,
        **snap,
    }


# ── Knowledge ──────────────────────────────────────────────


@router.get("/knowledge")
def knowledge_list(auth: AuthDep, db: Session = Depends(get_db)):
    docs = list_docs(db, auth.workspace.id)
    return [
        {
            "id": d.id,
            "title": d.title,
            "filename": d.filename,
            "source_type": d.source_type,
            "chunk_count": d.chunk_count,
            "preview": d.content_preview[:200],
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.post("/knowledge")
async def knowledge_upload(
    auth: AuthDep,
    file: UploadFile = File(...),
    title: str = Form(""),
    source_type: str = Form("policy"),
    db: Session = Depends(get_db),
):
    assert_can_upload_doc(db, auth)
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".markdown", ".docx"}:
        raise HTTPException(400, "Supported: PDF, TXT, MD, DOCX")

    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        doc = await ingest_document(
            db,
            dest,
            title=title or Path(file.filename).stem,
            workspace_id=auth.workspace.id,
            source_type=source_type if source_type in {"policy", "past_answer"} else "policy",
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    finally:
        if dest.exists():
            dest.unlink(missing_ok=True)

    return {"id": doc.id, "title": doc.title, "chunk_count": doc.chunk_count}


@router.delete("/knowledge/{doc_id}")
def knowledge_delete(doc_id: int, auth: AuthDep, db: Session = Depends(get_db)):
    if not delete_doc(db, doc_id, auth.workspace.id):
        raise HTTPException(404, "Document not found")
    return {"ok": True}


# ── Questionnaires ─────────────────────────────────────────


def _get_qn_or_404(db: Session, qn_id: int, workspace_id: int) -> Questionnaire:
    qn = db.get(Questionnaire, qn_id)
    if not qn or qn.workspace_id != workspace_id:
        raise HTTPException(404, "Not found")
    return qn


def _get_q_or_404(db: Session, question_id: int, workspace_id: int) -> Question:
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "Not found")
    qn = db.get(Questionnaire, q.questionnaire_id)
    if not qn or qn.workspace_id != workspace_id:
        raise HTTPException(404, "Not found")
    return q


@router.get("/questionnaires")
def qn_list(auth: AuthDep, db: Session = Depends(get_db)):
    items = (
        db.query(Questionnaire)
        .filter(Questionnaire.workspace_id == auth.workspace.id)
        .order_by(Questionnaire.created_at.desc())
        .all()
    )
    return [
        {
            "id": q.id,
            "name": q.name,
            "filename": q.filename,
            "status": q.status,
            "question_count": q.question_count,
            "answered_count": q.answered_count,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        }
        for q in items
    ]


@router.post("/questionnaires")
async def qn_upload(
    auth: AuthDep,
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm"}:
        raise HTTPException(400, "Supported: CSV, XLSX")

    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parsed = parse_questionnaire(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e)) from e

    assert_can_upload_questionnaire(db, auth, len(parsed))

    qn = Questionnaire(
        workspace_id=auth.workspace.id,
        name=name or Path(file.filename).stem,
        filename=dest.name,
        status="uploaded",
        question_count=len(parsed),
    )
    db.add(qn)
    db.flush()
    for item in parsed:
        db.add(
            Question(
                questionnaire_id=qn.id,
                row_number=item["row_number"],
                section=item.get("section") or "",
                question_text=item["question_text"],
                answer_text=item.get("existing_answer") or "",
                status="pending",
            )
        )
    db.commit()
    db.refresh(qn)
    record_questionnaire_upload(db, auth.workspace.id)
    return {
        "id": qn.id,
        "name": qn.name,
        "question_count": qn.question_count,
        "status": qn.status,
    }


@router.get("/questionnaires/{qn_id}")
def qn_detail(qn_id: int, auth: AuthDep, db: Session = Depends(get_db)):
    qn = _get_qn_or_404(db, qn_id, auth.workspace.id)
    questions = (
        db.query(Question)
        .filter(Question.questionnaire_id == qn_id)
        .order_by(Question.row_number)
        .all()
    )
    return {
        "id": qn.id,
        "name": qn.name,
        "status": qn.status,
        "question_count": qn.question_count,
        "answered_count": qn.answered_count,
        "questions": [
            {
                "id": q.id,
                "row_number": q.row_number,
                "section": q.section,
                "question_text": q.question_text,
                "answer_text": q.answer_text,
                "confidence": q.confidence,
                "status": q.status,
                "notes": q.notes,
                "from_library": bool(q.from_library),
                "sources": json.loads(q.sources or "[]"),
            }
            for q in questions
        ],
    }


@router.post("/questionnaires/{qn_id}/generate")
async def qn_generate(qn_id: int, auth: AuthDep, db: Session = Depends(get_db)):
    _get_qn_or_404(db, qn_id, auth.workspace.id)
    try:
        result = await draft_all(db, qn_id, auth.workspace.id)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return {
        "id": result.id,
        "status": result.status,
        "answered_count": result.answered_count,
        "question_count": result.question_count,
    }


@router.post("/questions/{question_id}/generate")
async def question_generate(
    question_id: int, auth: AuthDep, db: Session = Depends(get_db)
):
    q = _get_q_or_404(db, question_id, auth.workspace.id)
    q = await draft_one(db, q, auth.workspace.id)
    return {
        "id": q.id,
        "answer_text": q.answer_text,
        "confidence": q.confidence,
        "status": q.status,
        "from_library": bool(q.from_library),
        "sources": json.loads(q.sources or "[]"),
    }


@router.patch("/questions/{question_id}")
def question_update(
    question_id: int,
    body: QuestionUpdate,
    auth: AuthDep,
    db: Session = Depends(get_db),
):
    q = _get_q_or_404(db, question_id, auth.workspace.id)
    if body.answer_text is not None:
        q.answer_text = body.answer_text
    if body.status is not None:
        if body.status not in {"pending", "drafted", "reviewed", "skipped"}:
            raise HTTPException(400, "Invalid status")
        q.status = body.status
    if body.notes is not None:
        q.notes = body.notes
    db.commit()

    # Save to library when reviewed or explicitly requested
    should_save = body.save_to_library or body.status == "reviewed"
    if should_save and q.answer_text.strip():
        try:
            assert_can_save_library(db, auth)
            upsert_library_answer(
                db,
                auth.workspace.id,
                q.question_text,
                q.answer_text,
                q.section,
            )
        except HTTPException:
            raise
        except Exception:
            pass

    qn = db.get(Questionnaire, q.questionnaire_id)
    if qn:
        answered = (
            db.query(Question)
            .filter(
                Question.questionnaire_id == qn.id,
                Question.answer_text != "",
            )
            .count()
        )
        qn.answered_count = answered
        db.commit()

    return {"ok": True, "id": q.id, "status": q.status}


@router.get("/questionnaires/{qn_id}/export")
def qn_export(
    qn_id: int,
    auth: AuthDep,
    format: str = "xlsx",
    db: Session = Depends(get_db),
):
    _get_qn_or_404(db, qn_id, auth.workspace.id)
    try:
        if format == "csv":
            path = export_svc.export_csv(db, qn_id)
            media = "text/csv"
        else:
            path = export_svc.export_xlsx(db, qn_id)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return FileResponse(path, media_type=media, filename=path.name)


@router.delete("/questionnaires/{qn_id}")
def qn_delete(qn_id: int, auth: AuthDep, db: Session = Depends(get_db)):
    qn = _get_qn_or_404(db, qn_id, auth.workspace.id)
    db.delete(qn)
    db.commit()
    return {"ok": True}


# ── Answer Library ─────────────────────────────────────────


@router.get("/library")
def library_list(auth: AuthDep, db: Session = Depends(get_db)):
    items = list_library(db, auth.workspace.id)
    return [
        {
            "id": it.id,
            "question_text": it.question_text,
            "answer_text": it.answer_text,
            "section": it.section,
            "times_used": it.times_used,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None,
        }
        for it in items
    ]


@router.post("/library")
def library_create(
    body: LibraryCreate, auth: AuthDep, db: Session = Depends(get_db)
):
    assert_can_save_library(db, auth)
    try:
        item = upsert_library_answer(
            db,
            auth.workspace.id,
            body.question_text,
            body.answer_text,
            body.section,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": item.id, "ok": True}


@router.delete("/library/{item_id}")
def library_delete(item_id: int, auth: AuthDep, db: Session = Depends(get_db)):
    if not delete_library_item(db, auth.workspace.id, item_id):
        raise HTTPException(404, "Not found")
    return {"ok": True}
