from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    AuthDep,
    clear_session,
    get_optional_user,
    hash_password,
    set_session,
    verify_password,
)
from app.database import User, Workspace, get_db
from app.services.plans import usage_snapshot
from app.services.rate_limit import SlidingWindowLimiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Brute-force guard: max 8 failed logins per email (+client IP) per 5 minutes.
_login_failures = SlidingWindowLimiter(max_events=8, window_seconds=300)


def _login_rate_key(request: Request, email: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{email}@{client}"


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=128)
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


def _user_out(user: User, workspace: Workspace | None = None) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "plan": user.plan,
        "workspace": (
            {"id": workspace.id, "name": workspace.name} if workspace else None
        ),
    }


@router.post("/register")
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already registered")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=(body.name or email.split("@")[0])[:120],
        plan="free",
    )
    db.add(user)
    db.flush()
    ws = Workspace(name=f"{user.name}'s Workspace", owner_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(user)
    db.refresh(ws)
    set_session(response, user.id)
    return _user_out(user, ws)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    rate_key = _login_rate_key(request, email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.password_hash):
        if not _login_failures.allow(rate_key):
            raise HTTPException(429, "Too many failed login attempts. Try again in a few minutes.")
        raise HTTPException(401, "Invalid email or password")
    _login_failures.reset(rate_key)
    ws = (
        db.query(Workspace)
        .filter(Workspace.owner_id == user.id)
        .order_by(Workspace.id.asc())
        .first()
    )
    set_session(response, user.id)
    return _user_out(user, ws)


@router.post("/logout")
def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(auth: AuthDep, db: Session = Depends(get_db)):
    snap = usage_snapshot(db, auth)
    out = _user_out(auth.user, auth.workspace)
    out["usage"] = snap
    return out


@router.get("/session")
def session_check(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    if not user:
        return {"authenticated": False}
    ws = (
        db.query(Workspace)
        .filter(Workspace.owner_id == user.id)
        .order_by(Workspace.id.asc())
        .first()
    )
    return {"authenticated": True, "user": _user_out(user, ws)}
