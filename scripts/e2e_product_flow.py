#!/usr/bin/env python3
"""
Full product flow E2E (in-process TestClient):

register → login → upload policy → upload questionnaire → generate →
review+library → second questionnaire reuses library → export →
billing mock upgrade → free-tier limit check
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate test DB
import os

os.environ["DATA_DIR"] = str(ROOT / "data" / "e2e_test")
os.environ["SEED_DEMO"] = "0"
os.environ["APP_SECRET"] = "e2e-secret"

# Reload config paths after env set — import after env
from app.config import DATA_DIR, DB_PATH  # noqa: E402

DATA_DIR.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()
    client = TestClient(app)
    samples = ROOT / "samples"

    # 1) Register
    r = client.post(
        "/api/auth/register",
        json={"email": "founder@example.com", "password": "secret12", "name": "Founder"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "free"
    print("✓ register", r.json()["email"], r.json()["workspace"])

    # 2) Me / status
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    print("✓ me", r.json()["usage"]["plan"])

    # 3) Upload knowledge
    with (samples / "sample_security_policy.txt").open("rb") as f:
        r = client.post(
            "/api/knowledge",
            files={"file": ("policy.txt", f, "text/plain")},
            data={"title": "Policy", "source_type": "policy"},
        )
    assert r.status_code == 200, r.text
    print("✓ knowledge", r.json())

    # 4) Upload questionnaire #1
    with (samples / "sample_questionnaire.csv").open("rb") as f:
        r = client.post(
            "/api/questionnaires",
            files={"file": ("q1.csv", f, "text/csv")},
            data={"name": "Customer A"},
        )
    assert r.status_code == 200, r.text
    qn1 = r.json()["id"]
    print("✓ questionnaire1", r.json())

    # 5) Generate
    r = client.post(f"/api/questionnaires/{qn1}/generate")
    assert r.status_code == 200, r.text
    assert r.json()["answered_count"] >= 15
    print("✓ generate1", r.json())

    # 6) Review first 5 → library
    detail = client.get(f"/api/questionnaires/{qn1}").json()
    for q in detail["questions"][:5]:
        r = client.patch(
            f"/api/questions/{q['id']}",
            json={
                "answer_text": q["answer_text"] or "Yes — reviewed standard answer.",
                "status": "reviewed",
                "save_to_library": True,
            },
        )
        assert r.status_code == 200, r.text
    lib = client.get("/api/library").json()
    assert len(lib) >= 5
    print("✓ library saved", len(lib), "items")

    # 7) Second questionnaire — library reuse
    with (samples / "sample_questionnaire.csv").open("rb") as f:
        r = client.post(
            "/api/questionnaires",
            files={"file": ("q2.csv", f, "text/csv")},
            data={"name": "Customer B"},
        )
    qn2 = r.json()["id"]
    r = client.post(f"/api/questionnaires/{qn2}/generate")
    assert r.status_code == 200, r.text
    detail2 = client.get(f"/api/questionnaires/{qn2}").json()
    from_lib = sum(1 for q in detail2["questions"] if q.get("from_library"))
    assert from_lib >= 3, f"expected library hits, got {from_lib}"
    print("✓ library reuse hits", from_lib)

    # 8) Export
    r = client.get(f"/api/questionnaires/{qn2}/export?format=xlsx")
    assert r.status_code == 200
    assert len(r.content) > 1000
    print("✓ export", len(r.content), "bytes")

    # 9) Billing mock upgrade
    r = client.post("/api/billing/checkout")
    assert r.status_code == 200
    assert r.json().get("mock") or r.json().get("ok")
    me = client.get("/api/auth/me").json()
    assert me["plan"] == "pro"
    print("✓ mock upgrade to pro")

    # 10) Tenant isolation: second user cannot see qn
    client2 = TestClient(app)
    r = client2.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "secret12", "name": "Other"},
    )
    assert r.status_code == 200
    r = client2.get(f"/api/questionnaires/{qn1}")
    assert r.status_code == 404
    print("✓ tenant isolation")

    # 11) Free tier limit with new free user
    client3 = TestClient(app)
    client3.post(
        "/api/auth/register",
        json={"email": "free@example.com", "password": "secret12"},
    )
    # force free
    client3.post("/api/billing/mock-downgrade")
    tiny = "Section,Question\nA," + ("x" * 10) + "\n"
    # upload 3 questionnaires ok, 4th should 402
    for i in range(3):
        r = client3.post(
            "/api/questionnaires",
            files={"file": (f"t{i}.csv", io.BytesIO(tiny.encode()), "text/csv")},
            data={"name": f"T{i}"},
        )
        assert r.status_code == 200, r.text
    r = client3.post(
        "/api/questionnaires",
        files={"file": ("t3.csv", io.BytesIO(tiny.encode()), "text/csv")},
        data={"name": "T3"},
    )
    assert r.status_code == 402, r.text
    print("✓ free tier monthly limit enforced")

    # Pages
    for path in ("/", "/login", "/register", "/pricing"):
        assert client.get(path).status_code == 200
    assert client.get("/app").status_code == 200
    print("✓ pages render")

    print("\n✅ Full product flow E2E passed.")


if __name__ == "__main__":
    main()
