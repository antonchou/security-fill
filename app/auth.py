"""Password hashing, signed session cookies, request dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import APP_SECRET, PLAN_LIMITS, SESSION_COOKIE, SESSION_MAX_AGE
from app.database import User, Workspace, get_db


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(APP_SECRET, salt="securityfill-session")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256$120000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def create_session_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def set_session(response: Response, user_id: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@dataclass
class AuthContext:
    user: User
    workspace: Workspace

    @property
    def plan(self) -> str:
        return self.user.plan or "free"

    @property
    def limits(self) -> dict:
        return PLAN_LIMITS.get(self.plan, PLAN_LIMITS["free"])


def get_optional_user(
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User | None:
    if not session:
        return None
    uid = read_session_token(session)
    if not uid:
        return None
    return db.get(User, uid)


def require_auth(
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> AuthContext:
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    uid = read_session_token(session)
    if not uid:
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    ws = (
        db.query(Workspace)
        .filter(Workspace.owner_id == user.id)
        .order_by(Workspace.id.asc())
        .first()
    )
    if not ws:
        ws = Workspace(name=f"{user.name or user.email}'s Workspace", owner_id=user.id)
        db.add(ws)
        db.commit()
        db.refresh(ws)
    return AuthContext(user=user, workspace=ws)


AuthDep = Annotated[AuthContext, Depends(require_auth)]
