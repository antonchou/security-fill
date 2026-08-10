from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.config import KNOWLEDGE_DIR
from app.database import KnowledgeChunk, KnowledgeDoc
from app.services.llm import cosine, embed_texts, keyword_overlap_score
from app.services.text_extract import chunk_text, extract_text


async def ingest_document(
    db: Session,
    file_path: Path,
    title: str,
    workspace_id: int,
    source_type: str = "policy",
) -> KnowledgeDoc:
    text = extract_text(file_path)
    if not text.strip():
        raise ValueError("No text could be extracted from the file.")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced zero chunks.")

    dest = KNOWLEDGE_DIR / f"ws{workspace_id}_{file_path.name}"
    if file_path.resolve() != dest.resolve():
        shutil.copy2(file_path, dest)

    doc = KnowledgeDoc(
        workspace_id=workspace_id,
        title=title or file_path.stem,
        filename=dest.name,
        source_type=source_type,
        content_preview=text[:400],
        chunk_count=len(chunks),
    )
    db.add(doc)
    db.flush()

    embeddings = await embed_texts(chunks)
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        db.add(
            KnowledgeChunk(
                doc_id=doc.id,
                chunk_index=i,
                content=chunk,
                embedding_json=json.dumps(emb),
            )
        )
    db.commit()
    db.refresh(doc)
    return doc


def list_docs(db: Session, workspace_id: int) -> list[KnowledgeDoc]:
    return (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.workspace_id == workspace_id)
        .order_by(KnowledgeDoc.created_at.desc())
        .all()
    )


def delete_doc(db: Session, doc_id: int, workspace_id: int) -> bool:
    doc = db.get(KnowledgeDoc, doc_id)
    if not doc or doc.workspace_id != workspace_id:
        return False
    path = KNOWLEDGE_DIR / doc.filename
    if path.exists():
        path.unlink()
    db.delete(doc)
    db.commit()
    return True


def _chunks_for_workspace(db: Session, workspace_id: int) -> list[KnowledgeChunk]:
    docs = (
        db.query(KnowledgeDoc.id)
        .filter(KnowledgeDoc.workspace_id == workspace_id)
        .all()
    )
    doc_ids = [d.id for d in docs]
    if not doc_ids:
        return []
    return (
        db.query(KnowledgeChunk)
        .options(joinedload(KnowledgeChunk.doc))
        .filter(KnowledgeChunk.doc_id.in_(doc_ids))
        .all()
    )


async def retrieve_async(
    db: Session, query: str, workspace_id: int, top_k: int = 5
) -> list[dict]:
    chunks = _chunks_for_workspace(db, workspace_id)
    if not chunks:
        return []

    first_emb = json.loads(chunks[0].embedding_json) if chunks[0].embedding_json else []
    q_list = await embed_texts([query])
    q_emb = q_list[0] if q_list else []

    scored: list[tuple[float, KnowledgeChunk]] = []
    for ch in chunks:
        emb = json.loads(ch.embedding_json) if ch.embedding_json else []
        kw = keyword_overlap_score(query, ch.content)
        if emb and q_emb and len(emb) == len(q_emb):
            vec = cosine(q_emb, emb)
            score = 0.7 * vec + 0.3 * kw
        else:
            score = kw
        scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, ch in scored[:top_k]:
        if score <= 0 and first_emb:
            continue
        doc = ch.doc
        results.append(
            {
                "chunk_id": ch.id,
                "doc_id": doc.id if doc else None,
                "doc_title": doc.title if doc else "Unknown",
                "source_type": doc.source_type if doc else "policy",
                "content": ch.content,
                "score": round(float(score), 4),
            }
        )
    return results[:top_k]
