"""OpenAI-compatible client + local embedding/keyword fallbacks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import httpx
import numpy as np

from app.config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_MODEL,
)


def has_llm() -> bool:
    return bool(OPENAI_API_KEY)


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    # Keep alnum words (English + simple CJK handled as chars later)
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{1,}", text)
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "your", "have",
        "are", "was", "were", "will", "can", "does", "do", "is", "of", "to",
        "in", "on", "or", "as", "by", "an", "be", "it", "at", "we", "our",
        "you", "please", "describe", "provide", "yes", "no", "if", "any",
    }
    return [w for w in words if w not in stop]


def local_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic bag-of-hashes embedding for offline retrieval."""
    vec = np.zeros(dim, dtype=np.float64)
    tokens = _tokenize(text)
    if not tokens:
        return vec.tolist()
    for tok in tokens:
        h = hashlib.sha256(tok.encode()).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not has_llm():
        return [local_embed(t) for t in texts]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/embeddings",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": OPENAI_EMBEDDING_MODEL, "input": texts},
        )
        if resp.status_code >= 400:
            # Fallback silently for robustness
            return [local_embed(t) for t in texts]
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]


async def chat_json(system: str, user: str) -> dict[str, Any]:
    """Ask the model for JSON. Falls back to heuristic structure."""
    if not has_llm():
        return {"_fallback": True}

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        if resp.status_code >= 400:
            return {"_fallback": True, "error": resp.text[:500]}
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"answer": content, "confidence": 0.4, "rationale": "non-json response"}


def keyword_overlap_score(query: str, doc: str) -> float:
    q = set(_tokenize(query))
    d = set(_tokenize(doc))
    if not q or not d:
        return 0.0
    inter = len(q & d)
    return inter / math.sqrt(len(q) * len(d))
