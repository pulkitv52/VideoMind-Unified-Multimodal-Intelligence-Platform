"""Shared job scopes and lease fences for processing modules."""

from sqlalchemy import text
from videomind.connectors.upload.validation import InvalidFile


def scope(job):
    return {
        "w": job["workspace_id"],
        "s": job["source_id"],
        "r": job["revision_id"],
        "run": job["processing_run_id"],
        "j": job["id"],
        "token": job["lease_token"],
    }


def fence(conn, values, lock=False):
    result = conn.execute(
        text(
            "SELECT id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j AND requested_by=app.actor_id() AND status='running' AND lease_token=:token AND lease_expires_at>now()"
            + (" FOR UPDATE" if lock else "")
        ),
        values,
    ).first()
    if not result:
        raise InvalidFile("LEASE_EXPIRED")
