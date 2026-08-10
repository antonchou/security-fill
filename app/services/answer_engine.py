"""Draft answers from knowledge base + answer library."""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.database import Question, Questionnaire
from app.services.answer_library import find_library_match, mark_library_used
from app.services.knowledge import retrieve_async
from app.services.llm import chat_json, has_llm


SYSTEM_PROMPT = """You are a security compliance analyst helping a vendor fill customer security questionnaires.
Rules:
1. Answer ONLY using the provided knowledge excerpts (policies, past answers). Do not invent certifications or controls.
2. If evidence is insufficient, say so clearly and suggest what document is needed.
3. Prefer concise, professional language suitable for enterprise security reviews.
4. For yes/no questions, start with Yes / No / Partial / Not applicable when possible.
5. Return strict JSON:
{
  "answer": "string",
  "confidence": 0.0-1.0,
  "rationale": "brief reason",
  "needs_human_review": true/false
}
"""


def _best_sentences(question: str, text: str, limit: int = 2) -> str:
    from app.services.llm import _tokenize

    q_tokens = set(_tokenize(question))
    parts = re.split(r"(?<=[.!?。])\s+", text)
    if len(parts) <= 1:
        parts = re.split(r"\n+", text)
    scored: list[tuple[int, str]] = []
    for p in parts:
        p = p.strip()
        if len(p) < 20:
            continue
        t = set(_tokenize(p))
        score = len(q_tokens & t)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    picked = [s for _, s in scored[:limit]]
    if not picked:
        return text[:400] + ("…" if len(text) > 400 else "")
    return " ".join(picked)


def _heuristic_answer(question: str, sources: list[dict]) -> dict:
    if not sources:
        return {
            "answer": (
                "[Insufficient evidence] No matching policy content found. "
                "Please upload a relevant security policy or past questionnaire answers, then re-run."
            ),
            "confidence": 0.05,
            "rationale": "No knowledge matches",
            "needs_human_review": True,
        }

    combined = " ".join(s["content"] for s in sources[:3])
    top = sources[0]
    snippet = _best_sentences(question, combined, limit=2)
    if len(snippet) > 600:
        snippet = snippet[:600].rsplit(" ", 1)[0] + "…"

    q_lower = question.lower()
    yes_no = bool(
        re.search(
            r"\b(do you|does your|is there|are you|have you|can you|is data|are backups)\b",
            q_lower,
        )
    )
    negative_cues = (
        "not provide",
        "do not",
        "don't",
        "are not used",
        "not permit",
        "prohibited",
        "not allow",
    )
    positive_cues = (
        "require",
        "enforced",
        "encrypted",
        "maintains",
        "performed",
        "available",
    )

    polarity = None
    snip_l = snippet.lower()
    if any(c in snip_l for c in negative_cues):
        if re.search(r"\b(do customers|shared|public internet|siem)\b", q_lower):
            polarity = "No"
    if polarity is None and yes_no:
        polarity = "Yes" if any(c in snip_l for c in positive_cues) else "Partial"

    if yes_no and polarity:
        answer = f"{polarity} — based on our documentation ({top['doc_title']}): {snippet}"
    else:
        answer = f"Per {top['doc_title']}: {snippet}"

    conf = min(0.85, 0.35 + float(top.get("score", 0)) * 0.6)
    return {
        "answer": answer,
        "confidence": round(conf, 3),
        "rationale": f"Keyword/embedding match score={top.get('score')}",
        "needs_human_review": conf < 0.55,
    }


async def draft_one(
    db: Session,
    question: Question,
    workspace_id: int,
    *,
    prefer_library: bool = True,
) -> Question:
    # 1) Answer library reuse
    if prefer_library:
        lib = find_library_match(db, workspace_id, question.question_text)
        if lib:
            question.answer_text = lib.answer_text
            question.confidence = 0.95
            question.sources = json.dumps(
                [
                    {
                        "title": "Answer Library",
                        "type": "library",
                        "score": 1.0,
                        "excerpt": lib.question_text[:200],
                    }
                ],
                ensure_ascii=False,
            )
            question.status = "drafted"
            question.from_library = 1
            mark_library_used(db, lib)
            db.add(question)
            db.commit()
            db.refresh(question)
            return question

    question.from_library = 0
    sources = await retrieve_async(
        db, question.question_text, workspace_id=workspace_id, top_k=5
    )
    source_payload = [
        {
            "title": s["doc_title"],
            "type": s["source_type"],
            "score": s["score"],
            "excerpt": s["content"][:800],
        }
        for s in sources
    ]

    if has_llm() and sources:
        user = json.dumps(
            {
                "question": question.question_text,
                "section": question.section,
                "knowledge": source_payload,
            },
            ensure_ascii=False,
        )
        result = await chat_json(SYSTEM_PROMPT, user)
        if result.get("_fallback"):
            result = _heuristic_answer(question.question_text, sources)
    else:
        result = _heuristic_answer(question.question_text, sources)

    question.answer_text = str(result.get("answer") or "").strip()
    try:
        question.confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        question.confidence = 0.3
    question.sources = json.dumps(source_payload, ensure_ascii=False)
    question.status = "drafted" if question.answer_text else "pending"
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


async def draft_all(
    db: Session, questionnaire_id: int, workspace_id: int
) -> Questionnaire:
    qn = db.get(Questionnaire, questionnaire_id)
    if not qn or qn.workspace_id != workspace_id:
        raise ValueError("Questionnaire not found")
    qn.status = "processing"
    db.commit()

    questions = (
        db.query(Question)
        .filter(Question.questionnaire_id == questionnaire_id)
        .order_by(Question.row_number)
        .all()
    )
    answered = 0
    for q in questions:
        if q.status == "reviewed" and q.answer_text:
            answered += 1
            continue
        await draft_one(db, q, workspace_id)
        if q.answer_text:
            answered += 1

    qn.answered_count = answered
    qn.status = "ready"
    db.commit()
    db.refresh(qn)
    return qn
