"""Administrative indexing lifecycle and baseline diagnostics; no search UI."""

from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from videomind.identity.service import actor
from videomind.infrastructure.database import transaction
from videomind.embeddings.client import Client
from videomind.embeddings.contracts import validate_prompts
from videomind.embeddings import generations as lifecycle
from videomind.embeddings.indexer import heavy
from videomind.embeddings.repository import neighbors

router = APIRouter(prefix="/workspaces/{w}/indexes")


@router.get("")
def status(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        if not conn.execute(text("SELECT app.member_of(:w)"), {"w": w}).scalar_one():
            raise HTTPException(404)
        can_manage = conn.execute(
            text("SELECT app.admin_of(:w)"), {"w": w}
        ).scalar_one()
        # Counts across private sources are administrator-only.
        if not can_manage:
            return {"can_manage": False, "generations": []}
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT g.*,p.fingerprint FROM app.index_generations g JOIN app.embedding_profiles p ON (p.workspace_id,p.id)=(g.workspace_id,g.profile_id) WHERE g.workspace_id=:w ORDER BY g.created_at DESC"
                ),
                {"w": w},
            ).mappings()
        ]
        for r in rows:
            r["coverage"] = lifecycle.coverage_for(conn, w, r["id"])
        state = (
            conn.execute(
                text("SELECT * FROM app.workspace_search_state WHERE workspace_id=:w"),
                {"w": w},
            )
            .mappings()
            .first()
        )
        return {
            "can_manage": True,
            "generations": rows,
            "state": dict(state) if state else None,
        }


class Recipe(BaseModel):
    query_prompt: str | None = Field(default=None, max_length=600)
    document_prompt: str | None = Field(default=None, max_length=600)


@router.post("", status_code=201)
def start(
    w: UUID,
    request: Request,
    body: Recipe | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        lifecycle.admin(conn, w)
    try:
        profile = Client().profile()
    except Exception:
        raise HTTPException(503, "Embedding service unavailable")
    if body:
        values = profile.model_dump()
        values.update(body.model_dump(exclude_none=True))
        try:
            profile = type(profile).model_validate(values)
            validate_prompts(profile)
        except ValueError:
            raise HTTPException(422, "Invalid prompt templates")
    with transaction(request.app.state.db, principal) as conn:
        gid = lifecycle.create(conn, w, principal, profile)
    return {"id": gid}


@router.post("/{g}/activate")
def activate(w: UUID, g: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        return lifecycle.promote(conn, w, g)


@router.post("/{g}/retry")
def retry(w: UUID, g: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        lifecycle.admin(conn, w)
        lifecycle.lock(conn, w)
        if not conn.execute(
            text(
                "SELECT id FROM app.index_generations WHERE workspace_id=:w AND id=:g AND status IN ('building','active','standby')"
            ),
            {"w": w, "g": g},
        ).first():
            raise HTTPException(404)
        conn.execute(
            text(
                "UPDATE app.embedding_jobs SET status='queued',attempt=0,error_code=NULL WHERE workspace_id=:w AND generation_id=:g AND status='failed'"
            ),
            {"w": w, "g": g},
        )
    return {"queued": True}


class Probe(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    ann: bool = False
    limit: int = Field(default=10, ge=1, le=100)
    source_id: UUID | None = None


@router.post("/probe")
def probe(w: UUID, body: Probe, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        lifecycle.admin(conn, w)
        pinned = lifecycle.pin(conn, w)
    try:
        with heavy(request.app.state.db):
            result = Client().encode(
                pinned["fingerprint"],
                "text",
                body.query,
                query=True,
                configuration=pinned["configuration"],
            )
    except Exception:
        raise HTTPException(503, "Query embedding unavailable")
    with transaction(request.app.state.db, principal) as conn:
        lifecycle.admin(conn, w)
        return {
            "generation_id": pinned["id"],
            "profile": pinned["fingerprint"],
            "items": neighbors(
                conn,
                w,
                pinned,
                result["parts"][0]["vector"],
                body.limit,
                body.ann,
                body.source_id,
            ),
        }
