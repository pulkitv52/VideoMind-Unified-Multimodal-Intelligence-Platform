"""Self-service signup and narrowly scoped administrative membership operations."""

from datetime import datetime, timedelta, timezone
import secrets
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool

from videomind.identity.access import workspace_capabilities
from videomind.identity.routes import login_gate
from videomind.identity.security import password_hash, token_hash
from videomind.identity.service import actor, COOKIE
from videomind.infrastructure.database import transaction

router = APIRouter()


def database_error(exc):
    code = getattr(exc.orig, "sqlstate", "")
    status, message = {
        "23505": (409, "Choose a different username."),
        "42501": (403, "This action is not allowed."),
        "54000": (
            409,
            "Account or collection capacity reached. Contact the workspace owner.",
        ),
        "22023": (422, "Invalid account or collection details."),
        "P0002": (404, "Member unavailable."),
        "40001": (409, "Membership changed. Refresh and try again."),
    }.get(code, (503, "Service unavailable. Try again shortly."))
    return HTTPException(status, message)


def destination(request):
    try:
        return UUID(request.app.state.settings.signup_workspace_id)
    except (ValueError, TypeError):
        return None


class Signup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)
    accept_workspace_access: Literal[True]

    @field_validator("password_confirmation")
    @classmethod
    def confirmation(cls, value, info):
        if value != info.data.get("password"):
            raise ValueError("Password confirmation does not match")
        return value

    @field_validator("username", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


@router.get("/auth/signup-info")
def signup_info(request: Request):
    w = destination(request)
    if w is None:
        return {"enabled": False}
    with transaction(request.app.state.db) as conn:
        enabled = conn.execute(
            text("SELECT enabled FROM auth.signup_policy(:w)"), {"w": w}
        ).scalar_one_or_none()
        return {"enabled": bool(enabled)}


def register(engine, workspace, body, old_token=None):
    hashed = password_hash(body.password)
    with transaction(engine) as conn:
        try:
            result = (
                conn.execute(
                    text("SELECT * FROM auth.register_member(:w,:name,:hash)"),
                    {"w": workspace, "name": body.username, "hash": hashed},
                )
                .mappings()
                .one()
            )
            if old_token:
                conn.execute(
                    text("DELETE FROM auth.sessions WHERE token_hash=:hash"),
                    {"hash": token_hash(old_token)},
                )
            token = secrets.token_urlsafe(32)
            conn.execute(
                text(
                    "INSERT INTO auth.sessions(token_hash,principal_id,expires_at) VALUES(:hash,:p,:expiry)"
                ),
                {
                    "hash": token_hash(token),
                    "p": result["principal_id"],
                    "expiry": datetime.now(timezone.utc) + timedelta(hours=8),
                },
            )
        except DBAPIError as exc:
            raise database_error(exc) from None
        return token


@router.post("/auth/signup", status_code=201)
async def signup(body: Signup, request: Request, response: Response):
    w = destination(request)
    if w is None:
        raise HTTPException(403, "Registration is unavailable.")
    try:
        pipe = request.app.state.redis.pipeline()
        pipe.incr("signup:" + str(w))
        pipe.expire("signup:" + str(w), 60, nx=True)
        count, _ = await run_in_threadpool(pipe.execute)
    except Exception:
        raise HTTPException(503, "Registration is temporarily unavailable.") from None
    if count > 10:
        raise HTTPException(429, "Too many signup attempts. Try again shortly.")
    async with login_gate:
        token = await run_in_threadpool(
            register, request.app.state.db, w, body, request.cookies.get(COOKIE)
        )
    response.set_cookie(
        COOKIE,
        token,
        max_age=8 * 3600,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    return {"authenticated": True, "role": "member"}


class RegistrationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/workspaces/{w}/registration")
def policy(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        caps = workspace_capabilities(conn, w)
        if not caps.can_view_analytics:
            raise HTTPException(403, "Workspace administrator required")
        row = (
            conn.execute(text("SELECT * FROM auth.signup_policy(:w)"), {"w": w})
            .mappings()
            .first()
        )
        return {
            "enabled": bool(row and row["enabled"]),
            "configured": w == destination(request),
            "can_change": caps.can_manage_roles and w == destination(request),
        }


@router.put("/workspaces/{w}/registration")
def change_policy(
    w: UUID,
    body: RegistrationPolicy,
    request: Request,
    principal: UUID = Depends(actor),
):
    if w != destination(request):
        raise HTTPException(403, "This is not the configured signup workspace.")
    with transaction(request.app.state.db, principal) as conn:
        workspace_capabilities(conn, w)
        try:
            conn.execute(
                text("SELECT app.set_signup_policy(:w,:enabled)"),
                {"w": w, "enabled": body.enabled},
            )
        except DBAPIError as exc:
            raise database_error(exc) from None
    return {"enabled": body.enabled}


class MemberChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    role: str | None = Field(default=None, pattern="^(admin|member)$")


@router.post("/workspaces/{w}/people/{target}")
def change_member(
    w: UUID,
    target: UUID,
    body: MemberChange,
    request: Request,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        if not workspace_capabilities(conn, w).can_manage_members:
            raise HTTPException(403, "Workspace administrator required")
        try:
            conn.execute(
                text("SELECT app.change_member(:w,:p,:version,:role)"),
                {"w": w, "p": target, "version": body.version, "role": body.role},
            )
        except DBAPIError as exc:
            raise database_error(exc) from None
    return {"updated": True}
