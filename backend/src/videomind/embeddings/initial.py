"""Initial self-service publication runs as the current authorized workspace owner."""

from fastapi import HTTPException
from sqlalchemy import text

from videomind.embeddings import generations
from videomind.infrastructure.database import transaction


def initialize(engine, client):
    with engine.connect() as conn:
        work = (
            conn.execute(text("SELECT * FROM app.initial_index_work()"))
            .mappings()
            .all()
        )
    for item in work:
        w, owner = item["workspace_id"], item["owner_id"]
        # Fetching the current profile is a private local service operation.
        profile = client.profile() if item["generation_id"] is None else None
        with transaction(engine, owner) as conn:
            generations.admin(conn, w)
            generations.lock(conn, w)
            fresh = (
                conn.execute(
                    text(
                        "SELECT * FROM app.initial_index_work() WHERE workspace_id=:w AND owner_id=app.actor_id()"
                    ),
                    {"w": w},
                )
                .mappings()
                .first()
            )
            if not fresh:
                continue
            gid = fresh["generation_id"]
            if gid is None:
                if profile is None:
                    continue
                gid = generations.create(conn, w, owner, profile)
                conn.execute(
                    text("SELECT app.remember_initial_index(:w,:g)"), {"w": w, "g": gid}
                )
            else:
                # Coverage conflicts are expected until all eligible jobs finish.
                # Use a savepoint so any failed promotion is fully rolled back.
                try:
                    with conn.begin_nested():
                        generations.promote(conn, w, gid)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
