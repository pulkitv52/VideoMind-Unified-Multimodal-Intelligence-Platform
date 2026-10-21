"""PostgreSQL-driven reconciliation independent of Redis/beat state."""

import time
from sqlalchemy import text
from videomind.config import get_settings
from videomind.assets.storage import sweep
from videomind.infrastructure.services import object_client
from videomind.infrastructure.database import database
from videomind.workers.celery_app import app

_MEDIA_DELIVERIES = {}


def tick(engine):
    with engine.connect() as conn:
        pending = (
            conn.execute(
                text(
                    "SELECT p.*,app.intake_priority(workspace_id,source_id,id) AS priority FROM app.intake_pending() p"
                )
            )
            .mappings()
            .all()
        )
    now = time.monotonic()
    for key, sent in list(_MEDIA_DELIVERIES.items()):
        if now - sent >= 60:
            _MEDIA_DELIVERIES.pop(key, None)
    for job in pending:
        key = str(job["id"])
        if job["priority"] == 6 and key in _MEDIA_DELIVERIES:
            continue
        # Duplicates are safe: claim happens transactionally in PostgreSQL, never in Redis.
        app.send_task(
            "videomind.intake",
            args=[str(job["workspace_id"]), str(job["source_id"]), str(job["id"])],
            retry=False,
            priority=job["priority"],
        )
        if job["priority"] == 6:
            _MEDIA_DELIVERIES[key] = now


def main():
    settings = get_settings()
    engine = database(settings.database_url.get_secret_value())
    objects = object_client(settings)
    while True:
        try:
            tick(engine)
        except Exception:
            pass  # Do not emit connection strings or imported payloads.
        try:
            sweep(engine, objects, settings)
        except Exception:
            pass  # Durable cursor and retained references make the next pass safe.
        time.sleep(5)


if __name__ == "__main__":
    main()
