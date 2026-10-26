"""Authenticated source setup, bounded uploads, and intake inspection."""

import asyncio
import json
from pathlib import Path
import tempfile
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from videomind.connectors.local_folder.reader import folder_fd, relative_folder
from videomind.connectors.upload.validation import InvalidFile, filename
from videomind.identity.service import actor
from videomind.infrastructure.database import transaction
from videomind.infrastructure.telemetry import correlation_id, trace_id
from videomind.ingestion.service import ingest, source_scope

router = APIRouter()
upload_gate = asyncio.Semaphore(2)


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    connector_kind: Literal["upload", "local_folder"] = "upload"
    folder: str = Field(default="", max_length=200)


def workspace_admin(conn, w):
    if not conn.execute(
        text("SELECT id FROM app.workspaces WHERE id=:w"), {"w": w}
    ).first():
        raise HTTPException(404, "Workspace unavailable")
    if not conn.execute(text("SELECT app.admin_of(:w)"), {"w": w}).scalar_one():
        raise HTTPException(403, "Workspace administrator required")


def sync_job(conn, w, s, principal):
    existing = (
        conn.execute(
            text(
                "SELECT id,status FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND kind='folder_sync' AND status IN ('queued','running') LIMIT 1"
            ),
            {"w": w, "s": s},
        )
        .mappings()
        .first()
    )
    if existing:
        return dict(existing)
    return dict(
        conn.execute(
            text(
                "INSERT INTO app.ingestion_jobs(workspace_id,source_id,kind,requested_by,dedupe_key,trace_id) VALUES (:w,:s,'folder_sync',:p,:dedupe,:trace) RETURNING id,status"
            ),
            {
                "w": w,
                "s": s,
                "p": principal,
                "dedupe": str(uuid4()),
                "trace": correlation_id(trace_id.get()),
            },
        )
        .mappings()
        .one()
    )


@router.get("/workspaces/{w}/import-folders")
def import_folders(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        workspace_admin(conn, w)
    root = Path(request.app.state.settings.import_root)
    try:
        return {
            "folders": [""]
            + [
                p.name
                for p in sorted(root.iterdir())
                if not p.is_symlink() and p.is_dir()
            ]
        }
    except OSError:
        return {"folders": []}


@router.post("/workspaces/{w}/sources", status_code=201)
def create_source(
    w: UUID, body: SourceInput, request: Request, principal: UUID = Depends(actor)
):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Source name is required")
    config = {}
    with transaction(request.app.state.db, principal) as conn:
        if body.connector_kind == "upload":
            if body.folder:
                raise HTTPException(422, "Upload collections do not take a folder path")
            from videomind.identity.self_service import database_error
            from sqlalchemy.exc import DBAPIError

            try:
                source_id = conn.execute(
                    text("SELECT app.create_upload_collection(:w,:name)"),
                    {"w": w, "name": name},
                ).scalar_one()
            except DBAPIError as exc:
                raise database_error(exc) from None
            return {
                "id": source_id,
                "name": name,
                "connector_kind": "upload",
                "status": "connected",
            }
        workspace_admin(conn, w)
        if body.connector_kind == "local_folder":
            try:
                relative = relative_folder(body.folder)
                with folder_fd(request.app.state.settings.import_root, relative):
                    pass
                config = {"folder": relative}
            except (OSError, InvalidFile):
                raise HTTPException(
                    422, "Choose an available read-only import folder"
                ) from None
        elif body.folder:
            raise HTTPException(422, "Upload collections do not take a folder path")
        row = {
            "id": uuid4(),
            "name": name,
            "connector_kind": body.connector_kind,
            "status": "connected",
        }
        # RETURNING invokes SELECT RLS inside the insert's snapshot, before the
        # source-existence policy can observe the new row. Return generated fields.
        conn.execute(
            text(
                "INSERT INTO app.sources(workspace_id,id,name,connector_kind,config,status) VALUES (:w,:id,:name,:kind,CAST(:config AS jsonb),'connected')"
            ),
            {
                "w": w,
                "id": row["id"],
                "name": name,
                "kind": body.connector_kind,
                "config": json.dumps(config),
            },
        )
        if body.connector_kind == "local_folder":
            sync_job(conn, w, row["id"], principal)
        return row


@router.post("/workspaces/{w}/sources/{s}/files", status_code=202)
async def upload(
    w: UUID,
    s: UUID,
    request: Request,
    filename_value: str,
    principal: UUID = Depends(actor),
):
    try:
        name = filename(filename_value)
    except InvalidFile:
        raise HTTPException(422, "Invalid filename") from None
    with transaction(request.app.state.db, principal) as conn:
        source = source_scope(conn, w, s, write=True)
        if source["connector_kind"] != "upload":
            raise HTTPException(409, "Use folder sync for this source")
    maximum = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and (not declared.isdigit() or int(declared) > maximum):
        raise HTTPException(413, "File exceeds the 64 MiB limit")
    if upload_gate.locked():
        raise HTTPException(
            429, "Two uploads are already in progress; try again shortly"
        )
    async with upload_gate:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "original"
            try:
                async with asyncio.timeout(120):
                    with path.open("wb") as output:
                        size = 0
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > maximum:
                                raise HTTPException(
                                    413, "File exceeds the 64 MiB limit"
                                )
                            await run_in_threadpool(output.write, chunk)
                    return await run_in_threadpool(
                        ingest,
                        request.app.state.db,
                        request.app.state.objects,
                        request.app.state.settings,
                        principal,
                        w,
                        s,
                        path,
                        name,
                    )
            except InvalidFile as exc:
                raise HTTPException(
                    422, exc.code.replace("_", " ").capitalize()
                ) from None
            except TimeoutError:
                raise HTTPException(408, "Upload timed out; try again") from None


@router.post("/workspaces/{w}/sources/{s}/sync", status_code=202)
def sync(w: UUID, s: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        source = source_scope(conn, w, s, write=True, lock=True)
        if source["connector_kind"] != "local_folder":
            raise HTTPException(409, "This source accepts file uploads")
        return sync_job(conn, w, s, principal)


@router.get("/workspaces/{w}/sources/{s}/assets")
def assets(
    w: UUID,
    s: UUID,
    request: Request,
    response: Response,
    limit: int = Query(default=200, ge=1, le=200),
    after: UUID | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s)
        scope = {"w": w, "s": s, "after": after, "limit": limit + 1}
        page = (
            conn.execute(
                text(
                    """SELECT id,title,modality,mime_type,latest_revision_id FROM app.assets
          WHERE workspace_id=:w AND source_id=:s AND NOT deleted AND latest_revision_id IS NOT NULL
          AND (CAST(:after AS uuid) IS NULL OR (title,id)>(SELECT title,id FROM app.assets WHERE workspace_id=:w AND source_id=:s AND id=CAST(:after AS uuid) AND NOT deleted))
          ORDER BY title,id LIMIT :limit"""
                ),
                scope,
            )
            .mappings()
            .all()
        )
        revision_ids = [a["latest_revision_id"] for a in page]
        # Bounded, separately authorized batches avoid a nested-loop RLS plan
        # that rechecked every source row for each outer row. Never bypass RLS.
        revisions = {
            r["id"]: r
            for r in conn.execute(
                text(
                    "SELECT id,original_object_id,sha256 FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s AND id=ANY(CAST(:ids AS uuid[]))"
                ),
                dict(scope, ids=revision_ids),
            ).mappings()
        }
        object_ids = [r["original_object_id"] for r in revisions.values()]
        objects = {
            o["id"]: o
            for o in conn.execute(
                text(
                    "SELECT id,size_bytes FROM app.objects WHERE workspace_id=:w AND source_id=:s AND id=ANY(CAST(:ids AS uuid[]))"
                ),
                dict(scope, ids=object_ids),
            ).mappings()
        }
        jobs = {
            j["revision_id"]: j
            for j in conn.execute(
                text(
                    "SELECT revision_id,id AS job_id,status,error_code,manifest FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND kind='validate' AND revision_id=ANY(CAST(:ids AS uuid[]))"
                ),
                dict(scope, ids=revision_ids),
            ).mappings()
        }
        documents = {
            j["revision_id"]: dict(j)
            for j in conn.execute(
                text(
                    "SELECT DISTINCT ON (revision_id) revision_id,id AS job_id,status,error_code,manifest FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND kind='document' AND revision_id=ANY(CAST(:ids AS uuid[])) ORDER BY revision_id,created_at DESC"
                ),
                dict(scope, ids=revision_ids),
            ).mappings()
        }
        media = {
            j["revision_id"]: dict(j)
            for j in conn.execute(
                text(
                    "SELECT DISTINCT ON (revision_id) revision_id,id AS job_id,status,error_code,manifest FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND kind='media' AND revision_id=ANY(CAST(:ids AS uuid[])) ORDER BY revision_id,created_at DESC"
                ),
                dict(scope, ids=revision_ids),
            ).mappings()
        }
        indexed_revisions = set(
            conn.execute(
                text(
                    "SELECT ga.revision_id FROM app.generation_assets ga JOIN app.workspace_search_state ws ON (ws.workspace_id,ws.active_generation_id)=(ga.workspace_id,ga.generation_id) WHERE ga.workspace_id=:w AND ga.source_id=:s AND ga.revision_id=ANY(CAST(:ids AS uuid[]))"
                ),
                dict(scope, ids=revision_ids),
            ).scalars()
        )
        embedding_jobs = {
            j["revision_id"]: j["status"]
            for j in conn.execute(
                text(
                    "SELECT DISTINCT ON (j.revision_id) j.revision_id,j.status FROM app.embedding_jobs j JOIN app.index_generations g ON (g.workspace_id,g.id)=(j.workspace_id,j.generation_id) WHERE j.workspace_id=:w AND j.source_id=:s AND j.revision_id=ANY(CAST(:ids AS uuid[])) AND g.status IN ('building','active') ORDER BY j.revision_id,j.updated_at DESC"
                ),
                dict(scope, ids=revision_ids),
            ).mappings()
        }
        rows = []
        for asset in page:
            revision = revisions.get(asset["latest_revision_id"])
            if not revision or revision["original_object_id"] not in objects:
                continue
            row = dict(asset)
            row.pop("latest_revision_id")
            row.update(
                revision_id=revision["id"],
                sha256=revision["sha256"],
                size_bytes=objects[revision["original_object_id"]]["size_bytes"],
            )
            row.update(
                dict(
                    jobs.get(
                        revision["id"],
                        {
                            "job_id": None,
                            "status": None,
                            "error_code": None,
                            "manifest": {},
                        },
                    )
                )
            )
            row["document"] = documents.get(revision["id"])
            row["media"] = media.get(revision["id"])
            row["embedding_status"] = (
                "indexed"
                if revision["id"] in indexed_revisions
                else embedding_jobs.get(revision["id"])
            )
            rows.append(row)
        response.headers["X-Total-Count"] = str(
            conn.execute(
                text(
                    "SELECT count(*) FROM app.assets WHERE workspace_id=:w AND source_id=:s AND latest_revision_id IS NOT NULL AND NOT deleted"
                ),
                {"w": w, "s": s},
            ).scalar_one()
        )
        response.headers["X-Next-Cursor"] = (
            str(rows[limit - 1]["id"]) if len(rows) > limit else ""
        )
        return rows[:limit]


@router.get("/workspaces/{w}/sources/{s}/jobs")
def jobs(
    w: UUID,
    s: UUID,
    request: Request,
    response: Response,
    limit: int = Query(default=200, ge=1, le=200),
    after: UUID | None = None,
    kind: Literal["validate", "folder_sync", "document", "media"] | None = None,
    principal: UUID = Depends(actor),
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s)
        rows = [
            dict(row)
            for row in conn.execute(
                text(
                    """SELECT id,kind,status,attempt,error_code,manifest,trace_id,updated_at FROM app.ingestion_jobs
          WHERE workspace_id=:w AND source_id=:s AND (CAST(:kind AS text) IS NULL OR kind=:kind) AND (CAST(:after AS uuid) IS NULL OR (created_at,id)<(SELECT created_at,id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=CAST(:after AS uuid)))
          ORDER BY created_at DESC,id DESC LIMIT :limit"""
                ),
                {"w": w, "s": s, "after": after, "limit": limit + 1, "kind": kind},
            ).mappings()
        ]
        response.headers["X-Next-Cursor"] = (
            str(rows[limit - 1]["id"]) if len(rows) > limit else ""
        )
        return rows[:limit]


@router.post("/workspaces/{w}/sources/{s}/jobs/{j}/retry", status_code=202)
def retry(
    w: UUID, s: UUID, j: UUID, request: Request, principal: UUID = Depends(actor)
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s, write=True, lock=True)
        row = (
            conn.execute(
                text(
                    "UPDATE app.ingestion_jobs SET status='queued',attempt=0,requested_by=:p,lease_token=NULL,lease_expires_at=NULL,error_code=NULL,available_at=now(),updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND (status='failed' OR (kind='media' AND status='stored' AND manifest->>'partial'='true')) RETURNING id,status"
                ),
                {"w": w, "s": s, "j": j, "p": principal},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(409, "Only a failed intake job can be retried")
        return dict(row)


@router.delete("/workspaces/{w}/sources/{s}", status_code=204)
def disconnect(w: UUID, s: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s, lock=True)
        if not conn.execute(
            text("SELECT app.source_admin(:w,:s)"), {"w": w, "s": s}
        ).scalar_one():
            raise HTTPException(403, "Source administrator required")
        conn.execute(
            text("SELECT app.cancel_source_intake(:w,:s)"),
            {"w": w, "s": s},
        )
        conn.execute(
            text(
                "UPDATE app.assets SET deleted=true WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": s},
        )
        conn.execute(
            text(
                "UPDATE app.sources SET deleted=true,status='disconnected' WHERE workspace_id=:w AND id=:s"
            ),
            {"w": w, "s": s},
        )


@router.get("/workspaces/{w}/sources/{s}/assets/{a}/original")
def original(
    w: UUID, s: UUID, a: UUID, request: Request, principal: UUID = Depends(actor)
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s)
        row = (
            conn.execute(
                text("""SELECT a.title,o.object_key,o.size_bytes FROM app.assets a
          JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)=(a.workspace_id,a.source_id,a.latest_revision_id)
          JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id)
          WHERE a.workspace_id=:w AND a.source_id=:s AND a.id=:a AND NOT a.deleted"""),
                {"w": w, "s": s, "a": a},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Original unavailable")
    response = request.app.state.objects.get_object(
        request.app.state.settings.minio_bucket, row["object_key"]
    )

    def stream():
        try:
            yield from response.stream(1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(row["size_bytes"]),
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row["title"], safe=""),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/workspaces/{w}/sources/{s}/assets/{a}/retry-index")
def retry_file_index(
    w: UUID, s: UUID, a: UUID, request: Request, principal: UUID = Depends(actor)
):
    with transaction(request.app.state.db, principal) as conn:
        source_scope(conn, w, s, write=True, lock=True)
        result = conn.execute(
            text(
                """UPDATE app.embedding_jobs j SET status='queued',attempt=0,error_code=NULL
          FROM app.index_generations g,app.assets a
          WHERE (g.workspace_id,g.id)=(j.workspace_id,j.generation_id) AND g.status IN ('active','building')
          AND (a.workspace_id,a.source_id,a.id,a.latest_revision_id)=(j.workspace_id,j.source_id,j.asset_id,j.revision_id)
          AND j.workspace_id=:w AND j.source_id=:s AND j.asset_id=:a AND NOT a.deleted AND j.status='failed'"""
            ),
            {"w": w, "s": s, "a": a},
        )
        return {"queued": result.rowcount}


@router.get("/workspaces/{w}/storage")
def storage_usage(w: UUID, request: Request, principal: UUID = Depends(actor)):
    with transaction(request.app.state.db, principal) as conn:
        workspace_admin(conn, w)
        usage = conn.execute(
            text("SELECT app.storage_usage(:w)"), {"w": w}
        ).scalar_one()
    settings = request.app.state.settings
    return dict(
        usage,
        limit_bytes=settings.workspace_storage_bytes,
        limit_objects=settings.workspace_storage_objects,
    )
