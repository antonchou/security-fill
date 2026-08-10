"""Seed demo user for local product demos."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import DEMO_EMAIL, DEMO_PASSWORD, SEED_DEMO
from app.database import SessionLocal, User, Workspace


def ensure_demo_user() -> None:
    if not SEED_DEMO:
        return
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if user:
            return
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            name="Demo User",
            plan="pro",  # demo unlocked so reviewers can try full flow
        )
        db.add(user)
        db.flush()
        db.add(Workspace(name="Demo Workspace", owner_id=user.id))
        db.commit()
        print(f"[seed] demo user {DEMO_EMAIL} / {DEMO_PASSWORD}")
    finally:
        db.close()
