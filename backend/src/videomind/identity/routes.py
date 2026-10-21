import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from videomind.identity.security import token_hash
from videomind.identity.service import COOKIE, actor, authenticate
from videomind.infrastructure.database import transaction

router = APIRouter()
login_gate = asyncio.Semaphore(1)


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login")
async def login(credentials: Credentials, request: Request, response: Response):
    limiter_key = "login:" + token_hash(credentials.username.lower())
    try:
        pipe = request.app.state.redis.pipeline()
        pipe.incr(limiter_key)
        pipe.expire(limiter_key, 60, nx=True)
        count, _ = await run_in_threadpool(pipe.execute)
    except Exception:
        raise HTTPException(503, "Sign-in service unavailable") from None
    if count > 5:
        raise HTTPException(429, "Too many sign-in attempts; try again shortly")
    async with login_gate:
        token = await run_in_threadpool(
            authenticate,
            request.app.state.db,
            credentials.username,
            credentials.password,
            request.cookies.get(COOKIE),
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
    return {"authenticated": True}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db) as conn:
        conn.execute(
            text(
                "DELETE FROM auth.sessions WHERE token_hash=:hash AND principal_id=:id"
            ),
            {"hash": token_hash(request.cookies[COOKIE]), "id": principal},
        )
    response.delete_cookie(COOKIE, path="/api")


@router.get("/auth/me")
def me(request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        return dict(
            conn.execute(
                text("SELECT id, username FROM auth.principals WHERE id=:id"),
                {"id": principal},
            )
            .mappings()
            .one()
        )


@router.get("/workspaces")
def workspaces(request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT w.id,w.name,m.role FROM app.workspaces w JOIN app.memberships m ON m.workspace_id=w.id WHERE m.principal_id=:principal ORDER BY w.name,w.id"
                ),
                {"principal": principal},
            ).mappings()
        ]
