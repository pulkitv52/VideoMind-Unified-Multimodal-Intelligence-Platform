"""Durable original intake. Publication to search is a separate later phase."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from videomind.connectors.contracts import ConnectorItem
from videomind.assets.storage import admit, lock_writer, lock_publication
from videomind.connectors.upload.validation import inspect, InvalidFile
from videomind.connectors.upload.adapter import UploadConnector
from videomind.infrastructure.database import transaction
from videomind.infrastructure.telemetry import correlation_id, trace_id

PROFILE = hashlib.sha256(b"videomind-original-intake-v1").hexdigest()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_scope(conn, w, s, write=False, lock=False):
    if not conn.execute(
        text("SELECT id FROM auth.principals WHERE id=app.actor_id() AND NOT disabled")
    ).first():
        raise HTTPException(404, "Source unavailable")
    if lock:
        lock_publication(conn, w)
        # Ingest grants permit content writes, not source administration. A row's
        # FOR UPDATE lock invokes source-admin RLS, so serialize intake with a
        # source-scoped advisory lock while retaining ordinary SELECT policies.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
            {"scope": f"{w}/{s}"},
        )
    row = (
        conn.execute(
            text(
                "SELECT id,name,connector_kind,config FROM app.sources WHERE workspace_id=:w AND id=:s AND NOT deleted"
            ),
            {"w": w, "s": s},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Source unavailable")
    if (
        write
        and not conn.execute(
            text("SELECT app.source_access(:w,:s,true)"), {"w": w, "s": s}
        ).scalar_one()
    ):
        raise HTTPException(403, "Ingest permission required")
    return row


def ingest(
    engine,
    objects,
    settings,
    actor,
    w,
    s,
    path: Path,
    name,
    external_id=None,
    fence=None,
    connector_item: ConnectorItem | None = None,
):
    mime, modality = inspect(path, name)
    size = path.stat().st_size
    if size > settings.max_upload_bytes:
        raise HTTPException(413, "File exceeds the 64 MiB limit")
    sha = digest(path)
    item = (
        connector_item
        or asyncio.run(
            UploadConnector(path, name, w, s, settings.max_upload_bytes).discover(None)
        ).items[0]
    )
    if (
        item.workspace_id != w
        or item.source_id != s
        or item.sha256 != sha
        or item.size_bytes != size
        or item.mime_type != mime
        or item.permissions.state != "inherit_source"
    ):
        raise InvalidFile("SOURCE_REVISION_UNAVAILABLE")
    if external_id and item.external_id != external_id:
        raise InvalidFile("INVALID_CONNECTOR_ITEM")
    obj, rev, run, job = uuid4(), uuid4(), uuid4(), uuid4()
    key = f"{w}/{s}/originals/{obj}/{sha}"
    # Commit the quota reservation before any object bytes are written. This
    # survives a killed uploader, including a PUT followed by DB rollback.
    with transaction(engine, actor) as conn:
        lock_writer(conn, w)
        source_scope(conn, w, s, write=True)
        duplicate = conn.execute(
            text(
                "SELECT r.id FROM app.assets a JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.asset_id)=(a.workspace_id,a.source_id,a.id) WHERE a.workspace_id=:w AND a.source_id=:s AND a.external_id=:external AND r.sha256=:sha LIMIT 1"
            ),
            {"w": w, "s": s, "external": item.external_id, "sha": sha},
        ).first()
        if not duplicate:
            admit(conn, settings, w, s, size)
            conn.execute(
                text(
                    "INSERT INTO app.object_reservations(workspace_id,source_id,id,bucket,object_key,size_bytes) VALUES (:w,:s,:i,:b,:k,:size)"
                ),
                {
                    "w": w,
                    "s": s,
                    "i": obj,
                    "b": settings.minio_bucket,
                    "k": key,
                    "size": size,
                },
            )
    with transaction(engine, actor) as conn:
        lock_writer(conn, w)
        source = source_scope(conn, w, s, write=True, lock=True)
        if fence:
            valid = conn.execute(
                text(
                    "SELECT id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token AND status='running' AND lease_expires_at>now() FOR UPDATE"
                ),
                {"w": w, "s": s, "j": fence[0], "token": fence[1]},
            ).first()
            if not valid:
                raise HTTPException(409, "Job lease expired")
        scope = {"w": w, "s": s, "external": item.external_id}
        asset = (
            conn.execute(
                text(
                    "SELECT id,latest_revision_id FROM app.assets WHERE workspace_id=:w AND source_id=:s AND external_id=:external FOR UPDATE"
                ),
                scope,
            )
            .mappings()
            .first()
        )
        if not asset:
            asset = {"id": uuid4(), "latest_revision_id": None}
            conn.execute(
                text(
                    "INSERT INTO app.assets(workspace_id,source_id,id,external_id,title,modality,mime_type) VALUES (:w,:s,:a,:external,:name,:modality,:mime)"
                ),
                dict(scope, a=asset["id"], name=name, modality=modality, mime=mime),
            )
        existing = conn.execute(
            text(
                "SELECT id FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s AND asset_id=:a AND sha256=:sha ORDER BY created_at LIMIT 1"
            ),
            dict(scope, a=asset["id"], sha=sha),
        ).scalar()
        if existing:
            conn.execute(
                text(
                    "DELETE FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s AND id=:i"
                ),
                {"w": w, "s": s, "i": obj},
            )
            conn.execute(
                text(
                    "UPDATE app.assets SET latest_revision_id=:r,source_modified_at=:modified,deleted=false WHERE workspace_id=:w AND source_id=:s AND id=:a"
                ),
                dict(
                    scope, r=existing, a=asset["id"], modified=item.source_modified_at
                ),
            )
            job = (
                conn.execute(
                    text(
                        "SELECT id,status FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND revision_id=:r AND kind='validate'"
                    ),
                    dict(scope, r=existing),
                )
                .mappings()
                .one()
            )
            return {
                "asset_id": str(asset["id"]),
                "revision_id": str(existing),
                "job_id": str(job["id"]),
                "status": job["status"],
                "unchanged": asset["latest_revision_id"] == existing,
            }
        if not conn.execute(
            text(
                "SELECT id FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s AND id=:i"
            ),
            {"w": w, "s": s, "i": obj},
        ).first():
            raise HTTPException(409, "Intake reservation expired; retry the upload")
        with path.open("rb") as stream:
            objects.put_object(
                settings.minio_bucket,
                key,
                stream,
                size,
                content_type=mime,
                part_size=max(settings.max_upload_bytes, 5 * 1024**2),
                num_parallel_uploads=1,
            )
        values = {
            "w": w,
            "s": s,
            "a": asset["id"],
            "obj": obj,
            "rev": rev,
            "run": run,
            "job": job,
            "sha": sha,
            "mime": mime,
            "size": size,
            "bucket": settings.minio_bucket,
            "key": key,
            "profile": PROFILE,
            "actor": actor,
            "trace": correlation_id(trace_id.get()),
        }
        conn.execute(
            text(
                "INSERT INTO app.objects(workspace_id,source_id,id,bucket,object_key,sha256,size_bytes,mime_type,role) VALUES (:w,:s,:obj,:bucket,:key,:sha,:size,:mime,'original')"
            ),
            values,
        )
        conn.execute(
            text(
                "DELETE FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s AND id=:i"
            ),
            {"w": w, "s": s, "i": obj},
        )
        conn.execute(
            text(
                "INSERT INTO app.asset_revisions(workspace_id,source_id,id,asset_id,external_revision,sha256,original_object_id) VALUES (:w,:s,:rev,:a,:sha,:sha,:obj)"
            ),
            values,
        )
        conn.execute(
            text(
                "UPDATE app.assets SET latest_revision_id=:rev,mime_type=:mime,modality=:modality,source_created_at=coalesce(source_created_at,:created),source_modified_at=:modified,deleted=false WHERE workspace_id=:w AND source_id=:s AND id=:a"
            ),
            dict(
                values,
                modality=modality,
                created=item.source_created_at,
                modified=item.source_modified_at,
            ),
        )
        conn.execute(
            text(
                "INSERT INTO app.processing_runs(workspace_id,source_id,id,revision_id,profile_hash) VALUES (:w,:s,:run,:rev,:profile)"
            ),
            values,
        )
        conn.execute(
            text(
                "INSERT INTO app.stage_runs(workspace_id,source_id,processing_run_id,stage,configuration_hash,trace_id) VALUES (:w,:s,:run,'validate_original',:profile,:trace)"
            ),
            values,
        )
        conn.execute(
            text(
                "INSERT INTO app.outbox(workspace_id,source_id,processing_run_id,event_type,payload) VALUES (:w,:s,:run,'validate_original',jsonb_build_object('job_id',CAST(:job AS text)))"
            ),
            values,
        )
        conn.execute(
            text(
                "INSERT INTO app.ingestion_jobs(workspace_id,source_id,id,kind,revision_id,processing_run_id,requested_by,dedupe_key,trace_id) VALUES (:w,:s,:job,'validate',:rev,:run,:actor,CAST(:rev AS text),:trace)"
            ),
            values,
        )
        conn.execute(
            text(
                "UPDATE app.sources SET status='connected' WHERE workspace_id=:w AND id=:s"
            ),
            values,
        )
        return {
            "asset_id": str(asset["id"]),
            "revision_id": str(rev),
            "job_id": str(job),
            "status": "queued",
            "unchanged": False,
        }


def finish(engine, job, status, manifest=None, error=None):
    with transaction(engine, UUID(str(job["requested_by"]))) as conn:
        from videomind.assets.storage import lock_publication

        lock_publication(conn, job["workspace_id"])
        values = {
            "w": job["workspace_id"],
            "s": job["source_id"],
            "j": job["id"],
            "token": job["lease_token"],
            "status": status,
            "error": error,
            "manifest": json.dumps(manifest) if manifest is not None else None,
        }
        row = conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status=:status,error_code=:error,manifest=coalesce(CAST(:manifest AS jsonb),manifest),lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() AND EXISTS(SELECT FROM auth.principals WHERE id=app.actor_id() AND NOT disabled) RETURNING processing_run_id"
            ),
            values,
        ).first()
        if not row:
            return False
        return True
