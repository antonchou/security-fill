#!/usr/bin/env python3
"""End-to-end smoke test against a running server or in-process."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.database import Base, engine, init_db
from app.main import app


def main() -> None:
    # Fresh DB tables
    Base.metadata.drop_all(bind=engine)
    init_db()

    client = TestClient(app)
    samples = ROOT / "samples"

    r = client.get("/api/health")
    assert r.status_code == 200, r.text

    with (samples / "sample_security_policy.txt").open("rb") as f:
        r = client.post(
            "/api/knowledge",
            files={"file": ("sample_security_policy.txt", f, "text/plain")},
            data={"title": "Acme Security Policy", "source_type": "policy"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["chunk_count"] > 0
    print("✓ knowledge upload", r.json())

    with (samples / "sample_questionnaire.csv").open("rb") as f:
        r = client.post(
            "/api/questionnaires",
            files={"file": ("sample_questionnaire.csv", f, "text/csv")},
            data={"name": "Sample Vendor Q"},
        )
    assert r.status_code == 200, r.text
    qn_id = r.json()["id"]
    print("✓ questionnaire upload", r.json())

    r = client.post(f"/api/questionnaires/{qn_id}/generate")
    assert r.status_code == 200, r.text
    print("✓ generate", r.json())

    r = client.get(f"/api/questionnaires/{qn_id}")
    assert r.status_code == 200
    data = r.json()
    answered = sum(1 for q in data["questions"] if q["answer_text"])
    assert answered >= 10, f"expected many answers, got {answered}"
    # MFA question should mention multi-factor when policy loaded
    mfa = next(q for q in data["questions"] if "multi-factor" in q["question_text"].lower())
    assert mfa["answer_text"], "MFA answer empty"
    print("✓ sample MFA answer:", mfa["answer_text"][:160], "...")

    r = client.get(f"/api/questionnaires/{qn_id}/export?format=xlsx")
    assert r.status_code == 200
    assert len(r.content) > 1000
    print("✓ export xlsx", len(r.content), "bytes")

    r = client.get("/")
    assert r.status_code == 200
    print("✓ home page")

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
