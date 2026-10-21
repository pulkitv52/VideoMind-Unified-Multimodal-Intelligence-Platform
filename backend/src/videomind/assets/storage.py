"""Coordinate object writes, quota admission and bounded orphan reclamation."""

from datetime import datetime, timedelta, timezone
from itertools import islice

from fastapi import HTTPException
from sqlalchemy import text

# Writers share this lock across MinIO write + DB reference commit. Maintenance
# takes it exclusively, so an uncommitted live upload is never an orphan.
STORAGE_LOCK = 814207312


def lock_writer(conn, workspace):
    conn.execute(
        text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": STORAGE_LOCK}
    )
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:w,1))"),
        {"w": str(workspace)},
    )


def admit(conn, settings, workspace, source, size):
    allowed = conn.execute(
        text("SELECT app.storage_admit(:w,:s,:size,:budget,:objects)"),
        {
            "w": workspace,
            "s": source,
            "size": size,
            "budget": settings.workspace_storage_bytes,
            "objects": settings.workspace_storage_objects,
        },
    ).scalar_one()
    if not allowed:
        raise HTTPException(
            409,
            "Workspace storage limit reached; retention cleanup frees disconnected content after one hour",
        )


def sweep(engine, objects, settings):
    """One restart-safe batch; no paths/content are emitted into ordinary logs."""
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": STORAGE_LOCK}
        ).scalar_one():
            return {"busy": True}
        pending = (
            conn.execute(text("SELECT * FROM app.expired_reservations()"))
            .mappings()
            .all()
        )
        for item in pending:
            if not conn.execute(
                text("SELECT app.storage_referenced(:b,:k)"),
                {"b": item["bucket"], "k": item["object_key"]},
            ).scalar_one():
                objects.remove_object(item["bucket"], item["object_key"])
            conn.execute(
                text("SELECT app.release_reservation(:w,:s,:i)"),
                {"w": item["workspace_id"], "s": item["source_id"], "i": item["id"]},
            )
        retired = conn.execute(text("SELECT app.retire_intake()")).scalar_one()
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": STORAGE_LOCK}
        ).scalar_one():
            return dict(retired, busy=True)
        cursor = conn.execute(text("SELECT app.storage_cursor()")).scalar_one()
        # Lazy inventory, bounded to 32 keys. Cursor is committed only with this
        # batch; a kill after removal just repeats an idempotent remove next time.
        batch = list(
            islice(
                objects.list_objects(
                    settings.minio_bucket, recursive=True, start_after=cursor or None
                ),
                32,
            )
        )
        removed = 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        for item in batch:
            if item.last_modified is None or item.last_modified >= cutoff:
                continue
            referenced = conn.execute(
                text("SELECT app.storage_referenced(:b,:k)"),
                {"b": settings.minio_bucket, "k": item.object_name},
            ).scalar_one()
            if not referenced:
                objects.remove_object(settings.minio_bucket, item.object_name)
                removed += 1
        conn.execute(
            text("SELECT app.storage_cursor(:value)"),
            {"value": batch[-1].object_name if len(batch) == 32 else ""},
        )
        return dict(
            retired,
            scanned=len(batch),
            removed=removed,
            reservations_released=len(pending),
        )


def lock_publication(conn, workspace):
    """Order object/intake and index publication before any mutable row locks."""
    lock_writer(conn, workspace)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:w AS text),501))"),
        {"w": workspace},
    )
