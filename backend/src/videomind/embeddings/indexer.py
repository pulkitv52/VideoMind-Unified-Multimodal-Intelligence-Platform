"""PostgreSQL-driven embedding worker. Redis state is unnecessary for recovery."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import time
from uuid import UUID, uuid4
from sqlalchemy import text
from videomind.config import get_settings
from videomind.infrastructure.database import database, transaction
from videomind.infrastructure.services import object_client
from videomind.embeddings.client import Client
from videomind.embeddings.contracts import validate_vector, validate_result
from videomind.embeddings.generations import lock, reconcile, TARGETS


@contextmanager
def heavy(engine, blocking=True):
    # Session lock is released even after process death/socket loss.
    with engine.connect() as conn:
        if blocking:
            conn.execute(text("SELECT pg_advisory_lock(501,1)"))
        elif not conn.execute(text("SELECT pg_try_advisory_lock(501,1)")).scalar_one():
            yield False
            return
        try:
            yield True
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(501,1)"))


def values(job):
    return {
        "w": job["workspace_id"],
        "s": job["source_id"],
        "g": job["generation_id"],
        "j": job["id"],
        "token": job["lease_token"],
        "set": job["segment_set_id"],
        "asset": job["asset_id"],
    }


def fenced(conn, j):
    v = values(j)
    if not conn.execute(
        text(
            "SELECT id FROM app.embedding_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() AND EXISTS(SELECT FROM auth.principals WHERE id=app.actor_id() AND NOT disabled) FOR UPDATE"
        ),
        v,
    ).first():
        raise ValueError("LEASE_EXPIRED")
    if not conn.execute(
        text(
            "SELECT 1 FROM ("
            + TARGETS
            + ") t WHERE source_id=:s AND asset_id=:asset AND segment_set_id=:set"
        ),
        v,
    ).first():
        raise ValueError("INPUT_SUPERSEDED")


def claim(conn, w, g):
    conn.execute(
        text(
            "UPDATE app.embedding_jobs SET status='failed',error_code='EMBEDDING_INTERRUPTED',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND generation_id=:g AND status='running' AND lease_expires_at<now() AND attempt>=3"
        ),
        {"w": w, "g": g},
    )
    row = (
        conn.execute(
            text(
                "SELECT * FROM app.embedding_jobs WHERE workspace_id=:w AND generation_id=:g AND (status='queued' OR status='running' AND lease_expires_at<now()) ORDER BY updated_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
            ),
            {"w": w, "g": g},
        )
        .mappings()
        .first()
    )
    if not row:
        return
    j = dict(row)
    j["lease_token"] = uuid4()
    conn.execute(
        text(
            "UPDATE app.embedding_jobs SET status='running',attempt=attempt+1,lease_token=:token,lease_expires_at=now()+interval '30 seconds',error_code=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j"
        ),
        values(j),
    )
    return j


def read_object(conn, objects, settings, j, oid):
    v = dict(values(j), oid=oid)
    row = (
        conn.execute(
            text(
                "SELECT object_key,sha256,size_bytes FROM app.objects WHERE workspace_id=:w AND source_id=:s AND id=:oid"
            ),
            v,
        )
        .mappings()
        .one()
    )
    if row["size_bytes"] > 32 * 1024**2:
        raise ValueError("INPUT_TOO_LARGE")
    response = objects.get_object(settings.minio_bucket, row["object_key"])
    try:
        data = response.read(32 * 1024**2 + 1)
    finally:
        response.close()
        response.release_conn()
    if (
        len(data) != row["size_bytes"]
        or hashlib.sha256(data).hexdigest() != row["sha256"]
    ):
        raise ValueError("INPUT_HASH")
    return base64.b64encode(data).decode(), row["sha256"]


def prepare(conn, objects, settings, j, segment):
    rep = segment["representation"]
    manifest = {
        "adapter": "native-v1",
        "representation": rep,
        "producer": segment["producer"],
    }
    if rep in ("text", "ocr", "transcript"):
        kind = "text"
        content = segment["text_content"]
        manifest.update(
            text_sha256=hashlib.sha256(content.encode()).hexdigest(),
            title=segment["title"][:300],
        )
    elif rep in ("audio", "image"):
        kind = rep
        content, sha = read_object(
            conn, objects, settings, j, segment["derived_object_id"]
        )
        manifest["object_sha256"] = sha
    elif rep == "video":
        kind = "video"
        content = []
        frames = []
        for f in segment["transform"]["frames"]:
            data, sha = read_object(conn, objects, settings, j, f["object_id"])
            content.append(data)
            frames.append(dict(f, sha256=sha))
        manifest["frames"] = frames
        if not frames:
            raise ValueError("NO_FRAMES")
    else:
        raise ValueError("UNSUPPORTED_REPRESENTATION")
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return kind, content, manifest, digest


def publish_segment(conn, j, segment, profile, manifest, digest, result):
    validate_result(result, profile["fingerprint"])
    lock(conn, j["workspace_id"])
    fenced(conn, j)
    if result["profile"] != profile["fingerprint"]:
        raise ValueError("PROFILE_MISMATCH")
    count = conn.execute(
        text("SELECT count(*) FROM app.embeddings WHERE workspace_id=:w"), values(j)
    ).scalar_one()
    if count + len(result["parts"]) > 50000:
        raise ValueError("VECTOR_BUDGET")
    for part in result["parts"]:
        validate_vector(part["vector"])
        part_manifest = dict(
            manifest,
            input_hash=digest,
            start_unit=part["start_unit"],
            end_unit=part["end_unit"],
            tokens=part["tokens"],
            total_units=result["units"],
        )
        part_hash = hashlib.sha256(
            json.dumps(part_manifest, sort_keys=True).encode()
        ).hexdigest()
        conn.execute(
            text(
                "INSERT INTO app.embeddings(workspace_id,source_id,segment_id,profile_id,input_hash,input_manifest,embedding) VALUES(:w,:s,:seg,:p,:hash,CAST(:manifest AS jsonb),CAST(:vector AS vector)) ON CONFLICT DO NOTHING"
            ),
            dict(
                values(j),
                seg=segment["id"],
                p=profile["profile_id"],
                hash=part_hash,
                manifest=json.dumps(part_manifest),
                vector=json.dumps(part["vector"]),
            ),
        )


def process(engine, objects, settings, actor, j, client):
    with transaction(engine, actor) as conn:
        fenced(conn, j)
        p = dict(
            conn.execute(
                text(
                    "SELECT g.profile_id,p.fingerprint,p.configuration FROM app.index_generations g JOIN app.embedding_profiles p ON (p.workspace_id,p.id)=(g.workspace_id,g.profile_id) WHERE g.workspace_id=:w AND g.id=:g"
                ),
                values(j),
            )
            .mappings()
            .one()
        )
        segments = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT g.*,a.title,e.transform FROM app.segments g JOIN app.asset_revisions r ON (r.workspace_id,r.source_id,r.id)=(g.workspace_id,g.source_id,g.revision_id) JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(r.workspace_id,r.source_id,r.asset_id) JOIN app.segment_evidence se ON (se.workspace_id,se.source_id,se.segment_id)=(g.workspace_id,g.source_id,g.id) JOIN app.evidence_anchors e ON (e.workspace_id,e.source_id,e.id)=(se.workspace_id,se.source_id,se.anchor_id) WHERE g.workspace_id=:w AND g.source_id=:s AND g.segment_set_id=:set ORDER BY g.ordinal,g.id"
                ),
                values(j),
            ).mappings()
        ]
    if not segments:
        raise ValueError("EMPTY_INPUTS")
    for segment in segments:
        with transaction(engine, actor) as conn:
            fenced(conn, j)
            kind, content, manifest, digest = prepare(
                conn, objects, settings, j, segment
            )
            cached = conn.execute(
                text(
                    "SELECT input_manifest,embedding::text FROM app.embeddings WHERE workspace_id=:w AND source_id=:s AND segment_id=:seg AND profile_id=:p AND input_manifest->>'input_hash'=:digest ORDER BY (input_manifest->>'start_unit')::integer"
                ),
                dict(values(j), seg=segment["id"], p=p["profile_id"], digest=digest),
            ).all()
        if cached:
            offset = 0
            for m, _ in cached:
                if m["start_unit"] != offset:
                    raise ValueError("CACHE_COVERAGE")
                offset = m["end_unit"]
            if offset == cached[-1][0]["total_units"]:
                continue

        with transaction(engine, actor) as conn:
            reusable = conn.execute(
                text(
                    "SELECT DISTINCT ON ((input_manifest->>'start_unit')::integer) input_manifest,embedding::text FROM app.embeddings WHERE workspace_id=:w AND profile_id=:p AND input_manifest->>'input_hash'=:digest ORDER BY (input_manifest->>'start_unit')::integer"
                ),
                dict(values(j), p=p["profile_id"], digest=digest),
            ).all()
        if reusable:
            result = {
                "profile": p["fingerprint"],
                "units": reusable[-1][0]["total_units"],
                "parts": [
                    dict(
                        start_unit=m["start_unit"],
                        end_unit=m["end_unit"],
                        tokens=m["tokens"],
                        vector=json.loads(v),
                    )
                    for m, v in reusable
                ],
            }
            with transaction(engine, actor) as conn:
                publish_segment(conn, j, segment, p, manifest, digest, result)
            continue

        def encode():
            with heavy(engine):
                return client.encode(
                    p["fingerprint"],
                    kind,
                    content,
                    segment["title"],
                    configuration=p["configuration"],
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(encode)
            while not future.done():
                time.sleep(2)
                with transaction(engine, actor) as conn:
                    changed = conn.execute(
                        text(
                            "UPDATE app.embedding_jobs SET lease_expires_at=now()+interval '30 seconds',updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() RETURNING id"
                        ),
                        values(j),
                    ).first()
                    if not changed:
                        raise ValueError("LEASE_EXPIRED")
            result = future.result()
        with transaction(engine, actor) as conn:
            publish_segment(conn, j, segment, p, manifest, digest, result)
    with transaction(engine, actor) as conn:
        lock(conn, j["workspace_id"])
        fenced(conn, j)
        missing = conn.execute(
            text(
                "SELECT count(*) FROM app.segments s WHERE s.workspace_id=:w AND s.source_id=:s AND s.segment_set_id=:set AND NOT EXISTS(SELECT FROM app.embeddings e WHERE (e.workspace_id,e.source_id,e.segment_id)=(s.workspace_id,s.source_id,s.id) AND e.profile_id=:p)"
            ),
            dict(values(j), p=p["profile_id"]),
        ).scalar_one()
        if missing:
            raise ValueError("INCOMPLETE_COVERAGE")
        conn.execute(
            text(
                "INSERT INTO app.generation_assets(workspace_id,source_id,generation_id,asset_id,revision_id,segment_set_id) SELECT workspace_id,source_id,generation_id,asset_id,revision_id,segment_set_id FROM app.embedding_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j ON CONFLICT(workspace_id,source_id,generation_id,asset_id) DO UPDATE SET revision_id=excluded.revision_id,segment_set_id=excluded.segment_set_id"
            ),
            values(j),
        )
        conn.execute(
            text(
                "UPDATE app.assets a SET current_revision_id=:r WHERE a.workspace_id=:w AND a.source_id=:s AND a.id=:asset AND EXISTS(SELECT FROM app.index_generations WHERE workspace_id=:w AND id=:g AND status='active') AND a.current_revision_id IS DISTINCT FROM CAST(:r AS uuid)"
            ),
            dict(values(j), r=j["revision_id"]),
        )
        conn.execute(
            text(
                "UPDATE app.embedding_jobs SET status='ready',lease_token=NULL,lease_expires_at=NULL,manifest=CAST(:manifest AS jsonb),updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            dict(
                values(j),
                manifest=json.dumps({"segments": len(segments), "complete": True}),
            ),
        )


def tick(engine, objects, settings, client):
    from videomind.embeddings.initial import initialize

    try:
        initialize(engine, client)
    except Exception:
        # A failed first-index setup must not starve already registered work.
        pass
    with engine.connect() as conn:
        inventory = (
            conn.execute(text("SELECT * FROM app.index_pending()")).mappings().all()
        )
    for g in inventory:
        actor = g["requested_by"]
        with transaction(engine, actor) as conn:
            reconcile(conn, g["workspace_id"], g["generation_id"])
            j = claim(conn, g["workspace_id"], g["generation_id"])
        if not j:
            continue
        try:
            process(engine, objects, settings, actor, j, client)
        except Exception:
            with transaction(engine, actor) as conn:
                conn.execute(
                    text(
                        "UPDATE app.embedding_jobs SET status=CASE WHEN attempt>=3 THEN 'failed' ELSE 'queued' END,error_code='EMBEDDING_FAILED',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token AND lease_expires_at>now()"
                    ),
                    values(j),
                )


def main():
    settings = get_settings()
    engine = database(settings.database_url.get_secret_value())
    objects = object_client(settings)
    client = Client()
    while True:
        try:
            tick(engine, objects, settings, client)
        except Exception:
            pass  # Content and credentials never enter ordinary logs.
        time.sleep(3)


if __name__ == "__main__":
    main()
