from datetime import datetime, timedelta, timezone
from uuid import UUID
import secrets

from fastapi import HTTPException, Request
from sqlalchemy import text

from videomind.infrastructure.database import transaction
from videomind.identity.security import password_hash, token_hash, verify_password

COOKIE = "videomind_session"
# A missing username still pays the password verification cost.
DUMMY_HASH = password_hash(secrets.token_urlsafe(32))


def authenticate(engine, username: str, password: str, old_token: str | None):
    with transaction(engine) as conn:
        principal = (
            conn.execute(
                text(
                    "SELECT id, password_hash FROM auth.principals WHERE lower(username)=lower(:name) AND NOT disabled"
                ),
                {"name": username},
            )
            .mappings()
            .first()
        )
        valid = verify_password(
            password, principal["password_hash"] if principal else DUMMY_HASH
        )
        if not principal or not valid:
            raise HTTPException(401, "Invalid username or password")
        if old_token:
            conn.execute(
                text("DELETE FROM auth.sessions WHERE token_hash=:hash"),
                {"hash": token_hash(old_token)},
            )
        token = secrets.token_urlsafe(32)
        conn.execute(
            text(
                "INSERT INTO auth.sessions(token_hash, principal_id, expires_at) VALUES (:hash,:id,:expiry)"
            ),
            {
                "hash": token_hash(token),
                "id": principal["id"],
                "expiry": datetime.now(timezone.utc) + timedelta(hours=8),
            },
        )
        return token


def actor(request: Request) -> UUID:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(401, "Sign in to continue")
    with transaction(request.app.state.db) as conn:
        value = conn.execute(
            text(
                "SELECT s.principal_id FROM auth.sessions s JOIN auth.principals p ON p.id=s.principal_id WHERE s.token_hash=:hash AND s.expires_at>now() AND NOT p.disabled"
            ),
            {"hash": token_hash(token)},
        ).scalar_one_or_none()
    if value is None:
        raise HTTPException(401, "Session expired; sign in again")
    return value
