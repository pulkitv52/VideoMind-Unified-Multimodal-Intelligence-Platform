"""Generation lifecycle. Every writer fences against the workspace change epoch."""

import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import text
from videomind.embeddings.contracts import EmbeddingProfile

TARGETS = """
 SELECT a.workspace_id,a.source_id,a.id AS asset_id,a.latest_revision_id AS revision_id,ss.id AS segment_set_id,ss.manifest
 FROM app.assets a JOIN app.sources s ON (s.workspace_id,s.id)=(a.workspace_id,a.source_id)
 JOIN LATERAL (SELECT id,manifest FROM app.segment_sets ss WHERE ss.workspace_id=a.workspace_id AND ss.source_id=a.source_id
 AND ss.revision_id=a.latest_revision_id AND ss.status='ready' ORDER BY ss.created_at DESC,ss.id DESC LIMIT 1) ss ON true
 WHERE a.workspace_id=:w AND NOT a.deleted AND NOT s.deleted
"""


def lock(conn, w):
    from videomind.assets.storage import lock_publication

    lock_publication(conn, w)


def admin(conn, w):
    if not conn.execute(text("SELECT app.admin_of(:w)"), {"w": w}).scalar_one():
        raise HTTPException(404, "Workspace unavailable")


def create(conn, w, principal, profile: EmbeddingProfile):
    admin(conn, w)
    lock(conn, w)
    if (
        conn.execute(
            text("SELECT count(*) FROM app.index_generations WHERE workspace_id=:w"),
            {"w": w},
        ).scalar_one()
        >= 8
    ):
        raise HTTPException(409, "Local limit of eight retained generations reached")
    existing = conn.execute(
        text(
            "SELECT id FROM app.index_generations WHERE workspace_id=:w AND status='building'"
        ),
        {"w": w},
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "A generation is already building")
    pid = conn.execute(
        text(
            "INSERT INTO app.embedding_profiles(workspace_id,fingerprint,model_id,model_revision,configuration,dimension) VALUES(:w,:f,:model,:revision,CAST(:config AS jsonb),768) ON CONFLICT(workspace_id,fingerprint) DO NOTHING RETURNING id"
        ),
        {
            "w": w,
            "f": profile.fingerprint,
            "model": profile.model_id,
            "revision": profile.model_revision,
            "config": profile.model_dump_json(),
        },
    ).scalar_one_or_none()
    if not pid:
        pid = conn.execute(
            text(
                "SELECT id FROM app.embedding_profiles WHERE workspace_id=:w AND fingerprint=:f"
            ),
            {"w": w, "f": profile.fingerprint},
        ).scalar_one()
    gid = conn.execute(
        text(
            "INSERT INTO app.index_generations(workspace_id,profile_id,requested_by) VALUES(:w,:p,:actor) RETURNING id"
        ),
        {"w": w, "p": pid, "actor": principal},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO app.workspace_search_state(workspace_id) VALUES(:w) ON CONFLICT DO NOTHING"
        ),
        {"w": w},
    )
    # Each physical index is profile-specific; identical dimensions never imply compatibility.
    # pid is a server-generated UUID; interpolate only its canonical form.
    conn.execute(text(f"SELECT app.ensure_embedding_index(:w,:p)"), {"w": w, "p": pid})
    reconcile(conn, w, gid)
    return gid


def reconcile(conn, w, gid):
    lock(conn, w)
    g = (
        conn.execute(
            text(
                "SELECT * FROM app.index_generations WHERE workspace_id=:w AND id=:g AND status IN ('building','active','standby')"
            ),
            {"w": w, "g": gid},
        )
        .mappings()
        .first()
    )
    if not g:
        return
    conn.execute(
        text(
            "DELETE FROM app.generation_assets ga WHERE workspace_id=:w AND generation_id=:g AND NOT EXISTS(SELECT FROM app.assets a JOIN app.sources s ON (s.workspace_id,s.id)=(a.workspace_id,a.source_id) WHERE (a.workspace_id,a.source_id,a.id)=(ga.workspace_id,ga.source_id,ga.asset_id) AND NOT a.deleted AND NOT s.deleted)"
        ),
        {"w": w, "g": gid},
    )
    conn.execute(
        text(
            "INSERT INTO app.embedding_jobs(workspace_id,source_id,generation_id,asset_id,revision_id,segment_set_id) SELECT workspace_id,source_id,:g,asset_id,revision_id,segment_set_id FROM ("
            + TARGETS
            + ") t ON CONFLICT DO NOTHING"
        ),
        {"w": w, "g": gid},
    )
    # Cancel outdated in-flight work without disturbing a previous good publication.
    conn.execute(
        text(
            "UPDATE app.embedding_jobs j SET status='cancelled',lease_token=NULL WHERE workspace_id=:w AND generation_id=:g AND status IN ('queued','running') AND NOT EXISTS(SELECT FROM ("
            + TARGETS
            + ") t WHERE t.source_id=j.source_id AND t.asset_id=j.asset_id AND t.segment_set_id=j.segment_set_id)"
        ),
        {"w": w, "g": gid},
    )
    coverage = coverage_for(conn, w, gid)
    conn.execute(
        text(
            "UPDATE app.index_generations SET coverage=CAST(:c AS jsonb) WHERE workspace_id=:w AND id=:g"
        ),
        {"w": w, "g": gid, "c": json.dumps(coverage)},
    )
    return coverage


def coverage_for(conn, w, gid):
    targets = [dict(r) for r in conn.execute(text(TARGETS), {"w": w}).mappings()]
    published = {
        (r["source_id"], r["asset_id"], r["segment_set_id"])
        for r in conn.execute(
            text(
                "SELECT source_id,asset_id,segment_set_id FROM app.generation_assets WHERE workspace_id=:w AND generation_id=:g"
            ),
            {"w": w, "g": gid},
        ).mappings()
    }
    states = {
        r["status"]: r["n"]
        for r in conn.execute(
            text(
                "SELECT status,count(*) AS n FROM app.embedding_jobs WHERE workspace_id=:w AND generation_id=:g GROUP BY status"
            ),
            {"w": w, "g": gid},
        ).mappings()
    }
    total = conn.execute(
        text("SELECT count(*) FROM app.assets WHERE workspace_id=:w AND NOT deleted"),
        {"w": w},
    ).scalar_one()
    pending = conn.execute(
        text(
            "SELECT count(DISTINCT a.id) FROM app.assets a JOIN app.ingestion_jobs j ON (j.workspace_id,j.source_id,j.revision_id)=(a.workspace_id,a.source_id,a.latest_revision_id) WHERE a.workspace_id=:w AND NOT a.deleted AND j.status IN ('queued','running') AND j.kind IN ('validate','document','media')"
        ),
        {"w": w},
    ).scalar_one()
    return {
        "eligible_assets": len(targets),
        "published_assets": sum(
            (t["source_id"], t["asset_id"], t["segment_set_id"]) in published
            for t in targets
        ),
        "partial_extraction_assets": sum(
            bool(t["manifest"].get("partial")) for t in targets
        ),
        "assets_without_ready_inputs": total - len(targets),
        "pending_extraction_assets": pending,
        "jobs": states,
    }


def promote(conn, w, gid):
    admin(conn, w)
    lock(conn, w)
    row = (
        conn.execute(
            text(
                "SELECT * FROM app.index_generations WHERE workspace_id=:w AND id=:g FOR UPDATE"
            ),
            {"w": w, "g": gid},
        )
        .mappings()
        .first()
    )
    if not row or row["status"] not in ("building", "standby"):
        raise HTTPException(409, "Generation cannot be activated")
    reconcile(conn, w, gid)
    coverage = coverage_for(conn, w, gid)
    if (
        not coverage["eligible_assets"]
        or coverage["eligible_assets"] != coverage["published_assets"]
        or coverage["jobs"].get("running", 0)
        or coverage.get("pending_extraction_assets", 0)
        or coverage["jobs"].get("queued", 0)
    ):
        raise HTTPException(409, "Generation coverage is incomplete")
    conn.execute(
        text(
            "UPDATE app.assets a SET current_revision_id=ga.revision_id FROM app.generation_assets ga WHERE (ga.workspace_id,ga.source_id,ga.asset_id)=(a.workspace_id,a.source_id,a.id) AND ga.workspace_id=:w AND ga.generation_id=:g AND a.current_revision_id IS DISTINCT FROM ga.revision_id"
        ),
        {"w": w, "g": gid},
    )
    epoch = conn.execute(
        text(
            "SELECT content_epoch FROM app.workspace_search_state WHERE workspace_id=:w"
        ),
        {"w": w},
    ).scalar_one()
    conn.execute(
        text(
            "UPDATE app.index_generations SET status='standby' WHERE workspace_id=:w AND status='active'"
        ),
        {"w": w},
    )
    conn.execute(
        text(
            "UPDATE app.index_generations SET status='active',watermark=:epoch,coverage=CAST(:c AS jsonb) WHERE workspace_id=:w AND id=:g"
        ),
        {"w": w, "g": gid, "epoch": str(epoch), "c": json.dumps(coverage)},
    )
    conn.execute(
        text(
            "UPDATE app.workspace_search_state SET active_generation_id=:g,policy_epoch=policy_epoch+1 WHERE workspace_id=:w"
        ),
        {"w": w, "g": gid},
    )
    return coverage


def pin(conn, w):
    row = (
        conn.execute(
            text(
                "SELECT g.id,g.profile_id,p.fingerprint,p.configuration FROM app.workspace_search_state s JOIN app.index_generations g ON (g.workspace_id,g.id)=(s.workspace_id,s.active_generation_id) JOIN app.embedding_profiles p ON (p.workspace_id,p.id)=(g.workspace_id,g.profile_id) WHERE s.workspace_id=:w AND g.status='active'"
            ),
            {"w": w},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(409, "No active generation")
    return dict(row)
