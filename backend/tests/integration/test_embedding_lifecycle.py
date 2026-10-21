"""Real runtime-role generation publication, migration, fencing and exact/ANN tests."""

import json
from uuid import uuid4
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from test_foundation import foundation, insert, pytestmark
from videomind.infrastructure.database import transaction
from videomind.embeddings.contracts import EmbeddingProfile
from videomind.embeddings import generations as lifecycle
from videomind.embeddings.indexer import claim, publish_segment, fenced, values
from videomind.embeddings.repository import neighbors


def recipe(adapter="test-v1"):
    return EmbeddingProfile(
        model_revision="b" * 40,
        processor_revision="b" * 40,
        runtime_lock_sha256="a" * 64,
        input_adapter=adapter,
        preprocessing_hash="c" * 64,
    )


@pytest.fixture
def indexed(foundation):
    ids, owner, runtime, clients, *_ = foundation
    w, s, a, r, run, ss, seg, anchor, obj = [uuid4() for _ in range(9)]
    with owner.begin() as c:
        insert(c, "app.workspaces", id=w, name="Index lifecycle fixture")
        insert(
            c,
            "app.memberships",
            workspace_id=w,
            principal_id=ids["alice"],
            role="owner",
        )
        insert(
            c, "app.memberships", workspace_id=w, principal_id=ids["bob"], role="member"
        )
        insert(
            c,
            "app.sources",
            workspace_id=w,
            id=s,
            name="Private fixture",
            connector_kind="upload",
        )
        scope = {"workspace_id": w, "source_id": s}
        insert(
            c,
            "app.objects",
            **scope,
            id=obj,
            bucket="videomind",
            object_key=str(obj),
            sha256="a" * 64,
            size_bytes=1,
            mime_type="text/plain",
            role="original",
        )
        insert(
            c,
            "app.assets",
            **scope,
            id=a,
            external_id="fixture",
            title="Fixture",
            modality="document",
            mime_type="text/plain",
        )
        insert(
            c,
            "app.asset_revisions",
            **scope,
            id=r,
            asset_id=a,
            external_revision="v1",
            sha256="a" * 64,
            original_object_id=obj,
        )
        c.execute(
            text(
                "UPDATE app.assets SET current_revision_id=:r,latest_revision_id=:r WHERE id=:a"
            ),
            {"r": r, "a": a},
        )
        insert(
            c,
            "app.processing_runs",
            **scope,
            id=run,
            revision_id=r,
            profile_hash="c" * 64,
        )
        insert(
            c,
            "app.segment_sets",
            **scope,
            id=ss,
            revision_id=r,
            processing_run_id=run,
            segmenter_profile="fixture",
            status="ready",
        )
        insert(
            c,
            "app.segments",
            **scope,
            id=seg,
            segment_set_id=ss,
            revision_id=r,
            representation="text",
            ordinal=0,
            text_content="Safety instructions",
            producer="test",
        )
        insert(
            c,
            "app.evidence_anchors",
            **scope,
            id=anchor,
            revision_id=r,
            original_object_id=obj,
            locator_kind="page",
            page=1,
        )
        insert(
            c,
            "app.segment_evidence",
            **scope,
            segment_id=seg,
            anchor_id=anchor,
            revision_id=r,
            relation="extracted_from",
            producer="test",
        )
        insert(c, "app.citation_records", **scope, segment_id=seg, anchor_id=anchor)
    yield {
        "w": w,
        "s": s,
        "a": a,
        "r": r,
        "ss": ss,
        "seg": seg,
        "actor": ids["alice"],
        "bob": ids["bob"],
        "owner": owner,
        "runtime": runtime,
        "clients": clients,
    }
    with owner.begin() as c:
        # Partial HNSW indexes are schema objects, so fixture cleanup owns their DDL.
        for p in c.execute(
            text("SELECT id FROM app.embedding_profiles WHERE workspace_id=:w"),
            {"w": w},
        ).scalars():
            c.execute(text("DROP INDEX IF EXISTS app.embedding_hnsw_" + p.hex))
        c.execute(text("DELETE FROM app.sources WHERE workspace_id=:w"), {"w": w})
        c.execute(text("DELETE FROM app.workspaces WHERE id=:w"), {"w": w})


def build(f, adapter="test-v1"):
    with transaction(f["runtime"], f["actor"]) as c:
        g = lifecycle.create(c, f["w"], f["actor"], recipe(adapter))
        j = claim(c, f["w"], g)
        p = dict(
            c.execute(
                text(
                    "SELECT g.profile_id,p.fingerprint FROM app.index_generations g JOIN app.embedding_profiles p ON (p.workspace_id,p.id)=(g.workspace_id,g.profile_id) WHERE g.workspace_id=:w AND g.id=:g"
                ),
                {"w": f["w"], "g": g},
            )
            .mappings()
            .one()
        )
    return g, j, p


def store(f, j, p, vector=None):
    vector = vector or [1.0] + [0.0] * 767
    result = {
        "profile": p["fingerprint"],
        "units": 4,
        "parts": [{"start_unit": 0, "end_unit": 4, "tokens": 12, "vector": vector}],
    }
    with transaction(f["runtime"], f["actor"]) as c:
        publish_segment(
            c, j, {"id": f["seg"]}, p, {"representation": "text"}, "d" * 64, result
        )


def finish(f, j):
    with transaction(f["runtime"], f["actor"]) as c:
        lifecycle.lock(c, f["w"])
        fenced(c, j)
        c.execute(
            text(
                "INSERT INTO app.generation_assets(workspace_id,source_id,generation_id,asset_id,revision_id,segment_set_id) SELECT workspace_id,source_id,generation_id,asset_id,revision_id,segment_set_id FROM app.embedding_jobs WHERE id=:j"
            ),
            {"j": j["id"]},
        )
        c.execute(
            text(
                "UPDATE app.embedding_jobs SET status='ready',lease_token=NULL WHERE id=:j"
            ),
            {"j": j["id"]},
        )


def test_atomic_generation_pinning_profile_isolation_and_rollback(indexed):
    f = indexed
    g, j, p = build(f)
    store(f, j, p)
    store(f, j, p)  # duplicate delivery is idempotent
    with transaction(f["runtime"], f["actor"]) as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM app.embeddings WHERE workspace_id=:w"),
                {"w": f["w"]},
            ).scalar_one()
            == 1
        )
        assert lifecycle.coverage_for(c, f["w"], g)["published_assets"] == 0
        with pytest.raises(HTTPException):
            lifecycle.promote(c, f["w"], g)
    finish(f, j)
    with transaction(f["runtime"], f["actor"]) as c:
        lifecycle.promote(c, f["w"], g)
        pinned = lifecycle.pin(c, f["w"])
        exact = neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767)
        assert len(exact) == 1 and exact[0]["score"] == pytest.approx(1)
    with transaction(f["runtime"], f["actor"]) as c:
        ann = neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767, ann=True)
        assert ann == exact
    g2, j2, p2 = build(f, "new-profile")
    store(f, j2, p2, [0.0, 1.0] + [0.0] * 766)
    finish(f, j2)
    with transaction(f["runtime"], f["actor"]) as c:
        lifecycle.promote(c, f["w"], g2)
        assert neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767)[0][
            "score"
        ] == pytest.approx(1)
        current = lifecycle.pin(c, f["w"])
        assert current["id"] == g2
        assert neighbors(c, f["w"], current, [1.0] + [0.0] * 767)[0][
            "score"
        ] == pytest.approx(0)
        lifecycle.promote(c, f["w"], g)
        assert lifecycle.pin(c, f["w"])["id"] == g


def test_stale_worker_revocation_and_delete_fence(indexed):
    f = indexed
    g, j, p = build(f)
    with f["owner"].begin() as c:
        c.execute(
            text(
                "UPDATE app.embedding_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": j["id"]},
        )
    with pytest.raises(ValueError):
        store(f, j, p)
    with transaction(f["runtime"], f["actor"]) as c:
        new = claim(c, f["w"], g)
    assert new["lease_token"] != j["lease_token"]
    store(f, new, p)
    finish(f, new)
    with transaction(f["runtime"], f["actor"]) as c:
        lifecycle.promote(c, f["w"], g)
    with transaction(f["runtime"], f["bob"]) as c:
        assert not c.execute(
            text("SELECT * FROM app.embeddings WHERE workspace_id=:w"), {"w": f["w"]}
        ).first()
        with pytest.raises(HTTPException):
            lifecycle.promote(c, f["w"], g)
    with f["owner"].begin() as c:
        insert(
            c,
            "app.source_grants",
            workspace_id=f["w"],
            source_id=f["s"],
            principal_id=f["bob"],
            permission="read",
        )
    with transaction(f["runtime"], f["bob"]) as c:
        pinned = lifecycle.pin(c, f["w"])
        assert neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767)
    with f["owner"].begin() as c:
        c.execute(
            text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": f["s"]}
        )
    with transaction(f["runtime"], f["bob"]) as c:
        assert not neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767)
    with transaction(f["runtime"], f["actor"]) as c:
        c.execute(text("UPDATE app.assets SET deleted=true WHERE id=:a"), {"a": f["a"]})
    with transaction(f["runtime"], f["actor"]) as c:
        assert lifecycle.coverage_for(c, f["w"], g)["published_assets"] == 0
        assert not neighbors(c, f["w"], pinned, [1.0] + [0.0] * 767)


def test_replacement_during_build_and_invalid_vector(indexed):
    f = indexed
    g, j, p = build(f)
    with pytest.raises(ValueError):
        store(f, j, p, [0.0] * 768)
    with transaction(f["runtime"], f["actor"]) as c:
        assert not c.execute(
            text("SELECT * FROM app.embeddings WHERE workspace_id=:w"), {"w": f["w"]}
        ).first()
    # A newly ready segmentation supersedes the leased input before publication.
    with f["owner"].begin() as c:
        ss = uuid4()
        old = c.execute(
            text("SELECT processing_run_id FROM app.segment_sets WHERE id=:s"),
            {"s": f["ss"]},
        ).scalar_one()
        insert(
            c,
            "app.segment_sets",
            workspace_id=f["w"],
            source_id=f["s"],
            id=ss,
            revision_id=f["r"],
            processing_run_id=old,
            segmenter_profile="fixture-v2",
            status="ready",
        )
    with pytest.raises(ValueError):
        store(f, j, p)
    with transaction(f["runtime"], f["actor"]) as c:
        lifecycle.reconcile(c, f["w"], g)
        states = (
            c.execute(
                text("SELECT status FROM app.embedding_jobs WHERE workspace_id=:w"),
                {"w": f["w"]},
            )
            .scalars()
            .all()
        )
        assert "cancelled" in states and "queued" in states


def test_real_kill_after_vector_commit_resumes_without_reencoding(indexed):
    import os, signal, subprocess, sys
    from videomind.embeddings.indexer import process
    from videomind.config import Settings
    from videomind.infrastructure.database import database

    f = indexed
    g, j, p = build(f)
    # Run the actual prepare/publication code in an isolated producer and kill it
    # after its vector transaction commits, before generation membership exists.
    payload = json.dumps(
        {"job": j, "profile": p, "actor": f["actor"], "segment": f["seg"]}, default=str
    )
    code = """
import json,os,signal,sys
from sqlalchemy import text
from uuid import UUID
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
from videomind.embeddings.indexer import prepare,publish_segment
x=json.loads(sys.argv[1]);j=x['job'];actor=UUID(x['actor']);settings=Settings();engine=database(settings.database_url.get_secret_value())
with transaction(engine,actor) as c:
 s=dict(c.execute(text("SELECT g.*,'Fixture' AS title FROM app.segments g WHERE id=:id"),{'id':x['segment']}).mappings().one())
 kind,content,manifest,digest=prepare(c,None,settings,j,s)
 result={'profile':x['profile']['fingerprint'],'units':len(content),'parts':[{'start_unit':0,'end_unit':len(content),'tokens':30,'vector':[1.]+[0.]*767}]}
 publish_segment(c,j,s,x['profile'],manifest,digest,result)
os.kill(os.getpid(),signal.SIGKILL)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, payload], capture_output=True
    )
    assert completed.returncode == -signal.SIGKILL, completed.stderr.decode()[-500:]
    with f["owner"].begin() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM app.generation_assets WHERE workspace_id=:w"
                ),
                {"w": f["w"]},
            ).scalar_one()
            == 0
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM app.embeddings WHERE workspace_id=:w"),
                {"w": f["w"]},
            ).scalar_one()
            == 1
        )
        c.execute(
            text(
                "UPDATE app.embedding_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": j["id"]},
        )
    with transaction(f["runtime"], f["actor"]) as c:
        new = claim(c, f["w"], g)

    class NoInference:
        def encode(self, *args, **kwargs):
            raise AssertionError("Committed input must be reused")

    engine = database(Settings().database_url.get_secret_value())
    try:
        process(engine, None, Settings(), f["actor"], new, NoInference())
    finally:
        engine.dispose()
    with transaction(f["runtime"], f["actor"]) as c:
        assert lifecycle.coverage_for(c, f["w"], g)["published_assets"] == 1
        lifecycle.promote(c, f["w"], g)


def test_native_image_inputs_are_citable_and_source_scoped(foundation, tmp_path):
    from PIL import Image
    from test_phase2 import new_source
    from videomind.config import Settings
    from videomind.infrastructure.services import object_client
    from videomind.ingestion.service import ingest, finish
    from videomind.ingestion.worker import validate

    ids, owner, runtime, clients, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "photo.png"
    Image.new("RGB", (64, 48), "red").save(path)
    receipt = ingest(runtime, objects, settings, ids["alice"], w, s, path, "photo.png")
    with owner.begin() as c:
        job = c.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": w, "s": s, "j": receipt["job_id"]},
        ).scalar_one()
    assert job
    manifest = validate(runtime, objects, settings, job)
    assert finish(runtime, job, "stored", manifest)
    base = (
        f'/api/workspaces/{w}/sources/{s}/revisions/{receipt["revision_id"]}/document'
    )
    doc = clients["alice"].get(base)
    assert doc.status_code == 200
    assert doc.json()["manifest"]["kind"] == "image"
    assert len(doc.json()["pages"]) == 1
    detail = clients["alice"].get(base + "/pages/1").json()
    assert detail["text_object_id"] is None
    assert (
        len(detail["segments"]) == 1
        and detail["segments"][0]["representation"] == "image"
    )
    cite = detail["segments"][0]["citation_id"]
    url = f"/api/workspaces/{w}/sources/{s}/citations/{cite}"
    assert clients["alice"].get(url).json()["transform"]["box"] == [0, 0, 1, 1]
    assert clients["bob"].get(url).status_code == 404
    assert clients["bob"].get(base).status_code == 404
    image = clients["alice"].get(base + f'/objects/{detail["image_object_id"]}')
    assert image.status_code == 200 and image.content == path.read_bytes()
    # Repeated format completion does not duplicate the native segment set.
    with transaction(runtime, ids["alice"]) as c:
        from videomind.assets.storage import lock_publication

        lock_publication(c, w)
        c.execute(
            text("UPDATE app.ingestion_jobs SET status=status WHERE id=:j"),
            {"j": receipt["job_id"]},
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM app.segment_sets WHERE workspace_id=:w AND source_id=:s AND manifest->>'kind'='image'"
                ),
                {"w": w, "s": s},
            ).scalar_one()
            == 1
        )
    assert (
        clients["alice"].delete(f"/api/workspaces/{w}/sources/{s}").status_code == 204
    )
    assert clients["alice"].get(url).status_code == 404


def test_generation_identity_and_crash_retry_bound(indexed):
    from sqlalchemy.exc import DBAPIError

    f = indexed
    g, j, p = build(f)
    with pytest.raises(DBAPIError):
        with transaction(f["runtime"], f["actor"]) as c:
            c.execute(
                text(
                    "UPDATE app.index_generations SET requested_by=:actor WHERE workspace_id=:w AND id=:g"
                ),
                {"actor": f["bob"], "w": f["w"], "g": g},
            )
    with f["owner"].begin() as c:
        c.execute(
            text(
                "UPDATE app.embedding_jobs SET attempt=3,lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": j["id"]},
        )
    with transaction(f["runtime"], f["actor"]) as c:
        assert claim(c, f["w"], g) is None
        row = c.execute(
            text("SELECT status,error_code FROM app.embedding_jobs WHERE id=:j"),
            {"j": j["id"]},
        ).one()
        assert row == ("failed", "EMBEDDING_INTERRUPTED")


def test_source_removal_serializes_with_generation_cutover(indexed):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from videomind.config import Settings
    from videomind.infrastructure.database import database
    from videomind.ingestion.service import source_scope

    f = indexed
    g, j, p = build(f)
    store(f, j, p)
    finish(f, j)
    engine = database(Settings().database_url.get_secret_value())
    started = threading.Event()
    mutating = threading.Event()

    def remove():
        with transaction(engine, f["actor"]) as c:
            started.set()
            source_scope(c, f["w"], f["s"], write=True, lock=True)
            mutating.set()
            c.execute(
                text(
                    "UPDATE app.assets SET deleted=true WHERE workspace_id=:w AND source_id=:s AND id=:a"
                ),
                {"w": f["w"], "s": f["s"], "a": f["a"]},
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction(engine, f["actor"]) as c:
                lifecycle.lock(c, f["w"])
                future = pool.submit(remove)
                assert started.wait(5)
                assert not mutating.wait(0.2)
                lifecycle.promote(c, f["w"], g)
            future.result(timeout=10)
        with transaction(engine, f["actor"]) as c:
            assert mutating.is_set()
            assert lifecycle.coverage_for(c, f["w"], g)["published_assets"] == 0
            assert not neighbors(
                c, f["w"], lifecycle.pin(c, f["w"]), [1.0] + [0.0] * 767
            )
    finally:
        engine.dispose()
