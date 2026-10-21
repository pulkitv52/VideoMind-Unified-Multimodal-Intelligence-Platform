"""Idempotent intake tasks; database leases fence duplicate/stale delivery."""

import asyncio
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from videomind.config import get_settings
from videomind.connectors.local_folder.adapter import LocalFolderConnector
from videomind.connectors.upload.validation import InvalidFile
from videomind.infrastructure.database import database, transaction
from videomind.infrastructure.services import object_client
from videomind.infrastructure.telemetry import trace_id
from videomind.ingestion.service import finish, ingest


def probe_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def validate(engine, objects, settings, job):
    with transaction(engine, UUID(job["requested_by"])) as conn:
        row = (
            conn.execute(
                text(
                    "SELECT o.object_key,o.size_bytes,o.mime_type FROM app.asset_revisions r JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r"
                ),
                {
                    "w": job["workspace_id"],
                    "s": job["source_id"],
                    "r": job["revision_id"],
                },
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "Original unavailable")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "original"
        response = objects.get_object(settings.minio_bucket, row["object_key"])
        try:
            size = 0
            with path.open("wb") as output:
                for chunk in response.stream(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise InvalidFile("FILE_TOO_LARGE")
                    output.write(chunk)
        finally:
            response.close()
            response.release_conn()
        if size != row["size_bytes"]:
            raise InvalidFile("ORIGINAL_SIZE_MISMATCH")
        from videomind.ingestion.service import digest

        with transaction(engine, UUID(job["requested_by"])) as conn:
            expected = conn.execute(
                text(
                    "SELECT sha256 FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s AND id=:r"
                ),
                {
                    "w": job["workspace_id"],
                    "s": job["source_id"],
                    "r": job["revision_id"],
                },
            ).scalar_one()
        if digest(path) != expected:
            raise InvalidFile("ORIGINAL_HASH_MISMATCH")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "videomind.preprocessing.probe",
                str(path),
                row["mime_type"],
            ],
            capture_output=True,
            timeout=30,
            preexec_fn=probe_limits,
        )
        data = json.loads(result.stdout)
        if result.returncode or not data["ok"]:
            raise InvalidFile(
                "DOCUMENT_ENCRYPTED"
                if data.get("error_code") == "DOCUMENT_ENCRYPTED"
                else "STRUCTURAL_VALIDATION_FAILED"
            )
        return {
            "original_stored": True,
            "format_validated": True,
            "searchable": False,
            "metadata": data["metadata"],
        }


def sync_folder(engine, objects, settings, job):
    with transaction(engine, UUID(job["requested_by"])) as conn:
        config = conn.execute(
            text(
                "SELECT config FROM app.sources WHERE workspace_id=:w AND id=:s AND NOT deleted"
            ),
            {"w": job["workspace_id"], "s": job["source_id"]},
        ).scalar_one()
    connector = LocalFolderConnector(
        settings.import_root,
        config,
        UUID(job["workspace_id"]),
        UUID(job["source_id"]),
        settings.max_upload_bytes,
    )
    results = []
    seen = []

    async def consume():
        cursor = None
        while True:
            page = await connector.discover(cursor)
            for item in page.items:
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "original"
                    with path.open("wb") as output:
                        async for chunk in connector.fetch(item):
                            output.write(chunk)
                    result = ingest(
                        engine,
                        objects,
                        settings,
                        UUID(job["requested_by"]),
                        UUID(job["workspace_id"]),
                        UUID(job["source_id"]),
                        path,
                        item.name,
                        external_id=item.external_id,
                        fence=(job["id"], job["lease_token"]),
                        connector_item=item,
                    )
                    results.append(result)
                    seen.append(item.external_id)
                with transaction(engine, UUID(job["requested_by"])) as conn:
                    conn.execute(
                        text(
                            "UPDATE app.ingestion_jobs SET manifest=CAST(:manifest AS jsonb),updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token AND status='running' AND lease_expires_at>now()"
                        ),
                        {
                            "w": job["workspace_id"],
                            "s": job["source_id"],
                            "j": job["id"],
                            "token": job["lease_token"],
                            "manifest": json.dumps(
                                {
                                    "files_seen": len(seen),
                                    "files_expected": len(connector.items),
                                    "stage": "fetch",
                                    "searchable": False,
                                }
                            ),
                        },
                    )
            if page.complete:
                break
            cursor = page.next_cursor

    asyncio.run(consume())
    # Reconcile deletions only after a complete successful scan, never after a partial failure.
    with transaction(engine, UUID(job["requested_by"])) as conn:
        from videomind.ingestion.service import source_scope

        source_scope(conn, job["workspace_id"], job["source_id"], write=True, lock=True)
        valid = conn.execute(
            text(
                "SELECT id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token AND status='running' AND lease_expires_at>now() FOR UPDATE"
            ),
            {
                "w": job["workspace_id"],
                "s": job["source_id"],
                "j": job["id"],
                "token": job["lease_token"],
            },
        ).first()
        if not valid:
            raise InvalidFile("LEASE_EXPIRED")
        deleted = conn.execute(
            text(
                "UPDATE app.assets SET deleted=true WHERE workspace_id=:w AND source_id=:s AND NOT (external_id=ANY(CAST(:seen AS text[]))) AND NOT deleted RETURNING id"
            ),
            {"w": job["workspace_id"], "s": job["source_id"], "seen": seen},
        ).all()
        conn.execute(
            text(
                "UPDATE app.sources SET sync_cursor=:cursor WHERE workspace_id=:w AND id=:s"
            ),
            {
                "w": job["workspace_id"],
                "s": job["source_id"],
                "cursor": connector.snapshot_id,
            },
        )
    return {
        "files_seen": len(results),
        "files_expected": len(connector.items),
        "connector_cursor": connector.snapshot_id,
        "sync_mode": "full_manifest",
        "stage": "complete",
        "unchanged": sum(r["unchanged"] for r in results),
        "deleted": len(deleted),
        "searchable": False,
    }


def _execute(w, s, jid):
    settings = get_settings()
    engine = database(settings.database_url.get_secret_value())
    token = None
    try:
        with engine.begin() as conn:
            job = conn.execute(
                text("SELECT app.intake_claim(:w,:s,:j)"), {"w": w, "s": s, "j": jid}
            ).scalar_one()
        if not job:
            return
        token = trace_id.set(job["trace_id"])
        if job["processing_run_id"]:
            with transaction(engine, UUID(job["requested_by"])) as conn:
                values = {
                    "w": w,
                    "s": s,
                    "run": job["processing_run_id"],
                    "attempt": job["attempt"],
                    "token": job["lease_token"],
                }
                conn.execute(
                    text(
                        "UPDATE app.outbox SET published_at=now() WHERE workspace_id=:w AND source_id=:s AND processing_run_id=:run AND published_at IS NULL"
                    ),
                    values,
                )
        try:
            objects = object_client(settings)
            if job["kind"] == "media":
                from videomind.preprocessing.media.worker import process

                process(engine, objects, settings, job)
                return
            if job["kind"] == "document":
                from videomind.preprocessing.documents.worker import process

                process(engine, objects, settings, job)
                return
            manifest = (
                validate(engine, objects, settings, job)
                if job["kind"] == "validate"
                else sync_folder(engine, objects, settings, job)
            )
            finish(engine, job, "stored", manifest)
        except (InvalidFile, HTTPException, subprocess.TimeoutExpired) as exc:
            code = (
                exc.code
                if isinstance(exc, InvalidFile)
                else (
                    "VALIDATION_TIMEOUT"
                    if isinstance(exc, subprocess.TimeoutExpired)
                    else "SOURCE_UNAVAILABLE"
                )
            )
            finish(engine, job, "failed", error=code)
        except Exception:
            if job["attempt"] >= 3:
                finish(engine, job, "failed", error="INTAKE_UNAVAILABLE")
            else:
                with transaction(engine, UUID(job["requested_by"])) as conn:
                    values = {
                        "w": w,
                        "s": s,
                        "j": jid,
                        "token": job["lease_token"],
                        "run": job["processing_run_id"],
                    }
                    updated = conn.execute(
                        text(
                            "UPDATE app.ingestion_jobs SET status='queued',error_code='INTAKE_UNAVAILABLE',available_at=now()+interval '15 seconds',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() RETURNING id"
                        ),
                        values,
                    ).first()
    finally:
        if token is not None:
            trace_id.reset(token)
        engine.dispose()


def execute(w, s, jid):
    # Share the CPU-heavy gate with indexing; claim only after acquisition.
    from videomind.embeddings.indexer import heavy

    settings = get_settings()
    engine = database(settings.database_url.get_secret_value())
    try:
        with heavy(engine, blocking=False) as acquired:
            if acquired:
                return _execute(w, s, jid)
    finally:
        engine.dispose()
