"""Runtime-role media evidence, byte ranges, immutable citations and fault tests."""

import json
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from media_fixtures import video, audio
from test_foundation import foundation, insert, pytestmark
from test_phase2 import new_source, wait_sweep
from videomind.config import Settings
from videomind.infrastructure.database import transaction
from videomind.infrastructure.services import object_client
from videomind.ingestion.service import ingest
from videomind.preprocessing.media.worker import process
from videomind.connectors.upload.validation import InvalidFile


def prepared(foundation, tmp_path, nonzero=False):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    settings = Settings()
    objects = object_client(settings)
    path = video(tmp_path / "input.mp4", nonzero=nonzero)
    receipt = ingest(
        runtime, objects, settings, ids["alice"], w, s, path, "timeline.mp4"
    )
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE app.ingestion_jobs SET status='stored' WHERE id=:j"),
            {"j": receipt["job_id"]},
        )
        jid = conn.execute(
            text(
                "SELECT id FROM app.ingestion_jobs WHERE source_id=:s AND kind='media' FOR UPDATE"
            ),
            {"s": s},
        ).scalar_one()
        job = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"), {"w": w, "s": s, "j": jid}
        ).scalar_one()
    assert job
    return s, receipt, job, settings, objects


def test_range_playback_citations_and_revocation_in_existing_session(
    foundation, tmp_path
):
    ids, owner, runtime, clients, *_ = foundation
    s, receipt, job, settings, objects = prepared(foundation, tmp_path, nonzero=True)
    process(runtime, objects, settings, job)
    base = f'/api/workspaces/{ids["workspace"]}/sources/{s}'
    r = receipt["revision_id"]
    alice = clients["alice"]
    bob = clients["bob"]
    descriptor = alice.get(f"{base}/revisions/{r}/media")
    assert descriptor.status_code == 200
    doc = descriptor.json()
    ss = doc["segment_set_id"]
    assert doc["manifest"]["origin_ms"] == 5000
    rows = alice.get(f"{base}/revisions/{r}/media/segments").json()["items"]
    assert rows
    seg = rows[0]
    citation = f'{base}/citations/{seg["citation_id"]}'
    resolved = alice.get(citation)
    assert (
        resolved.status_code == 200
        and resolved.json()["locator_kind"] == "temporal"
        and resolved.json()["start_ms"] == 5000
    )
    url = f'{base}/revisions/{r}/media/objects/{doc["playback_object_id"]}?segment_set_id={ss}'
    full = alice.get(url)
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    part = alice.get(url, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(full.content)}"
    assert alice.get(url, headers={"Range": "bytes=-32"}).content == full.content[-32:]
    assert alice.get(url, headers={"Range": "bytes=100-"}).content == full.content[100:]
    assert alice.get(url, headers={"Range": "bytes=999999999-"}).status_code == 416
    assert alice.get(url, headers={"Range": "bytes=0-1,8-9"}).status_code == 416
    assert (
        alice.get(
            url, headers={"Range": "bytes=0-9", "If-Range": '"wrong"'}
        ).status_code
        == 200
    )
    head = alice.head(url)
    assert (
        head.status_code == 200
        and not head.content
        and int(head.headers["content-length"]) == len(full.content)
    )
    assert bob.get(url, headers={"Range": "bytes=0-9"}).status_code == 404
    unknown = f"{base}/revisions/{r}/media/objects/{uuid4()}"
    assert alice.get(unknown).status_code == 404
    with owner.begin() as conn:
        insert(
            conn,
            "app.source_grants",
            workspace_id=ids["workspace"],
            source_id=s,
            principal_id=ids["bob"],
            permission="read",
        )
    assert bob.get(url, headers={"Range": "bytes=0-9"}).status_code == 206
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": s})
    assert (
        bob.get(url, headers={"Range": "bytes=10-19"}).status_code == 404
        and bob.get(citation).status_code == 404
    )
    new = alice.post(
        base + "/files",
        params={"filename_value": "timeline.mp4"},
        content=video(tmp_path / "new.mp4").read_bytes(),
    ).json()
    assert new["revision_id"] != r
    assert alice.get(citation).json()["revision_id"] == r
    assert alice.get(url, headers={"Range": "bytes=0-9"}).status_code == 206
    assert alice.delete(base).status_code == 204
    assert (
        alice.get(url, headers={"Range": "bytes=20-29"}).status_code == 404
        and alice.get(citation).status_code == 404
    )


def test_stale_lease_and_quota_cannot_publish_partial_media(foundation, tmp_path):

    ids, owner, runtime, *_ = foundation
    s, receipt, old, settings, objects = prepared(foundation, tmp_path)
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": old["id"]},
        )
        job = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": old["workspace_id"], "s": s, "j": old["id"]},
        ).scalar_one()
    with pytest.raises(InvalidFile, match="LEASE_EXPIRED"):
        process(runtime, objects, settings, old)
    with pytest.raises(InvalidFile, match="MEDIA_STORAGE_LIMIT"):
        process(
            runtime,
            objects,
            settings.model_copy(update={"workspace_storage_bytes": 1}),
            job,
        )
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.media_presentations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.object_reservations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
    process(runtime, objects, settings, job)
    with pytest.raises(InvalidFile, match="LEASE_EXPIRED"):
        process(runtime, objects, settings, job)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.media_presentations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 1
        )


def test_sigkill_after_derivative_put_recovers_and_retention_preserves_live_media(
    foundation, tmp_path
):
    ids, owner, runtime, *_ = foundation
    s, receipt, job, settings, objects = prepared(foundation, tmp_path)
    fixture = tmp_path / "job.json"
    fixture.write_text(json.dumps(job))
    script = """
import json,os,signal,sys
from videomind.config import Settings
from videomind.infrastructure.database import database
from videomind.infrastructure.services import object_client
from videomind.preprocessing.media.worker import process
settings=Settings();engine=database(settings.database_url.get_secret_value());client=object_client(settings)
class KillAfterPut:
 def __getattr__(self,name):return getattr(client,name)
 def put_object(self,*a,**kw):
  result=client.put_object(*a,**kw);os.kill(os.getpid(),signal.SIGKILL)
process(engine,KillAfterPut(),settings,json.load(open(sys.argv[1])))
"""
    killed = subprocess.run(
        [sys.executable, "-c", script, str(fixture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=40,
    )
    assert killed.returncode == -signal.SIGKILL
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.media_presentations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.object_reservations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            > 0
        )
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": job["id"]},
        )
        new = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": job["workspace_id"], "s": s, "j": job["id"]},
        ).scalar_one()
    process(runtime, objects, settings, new)
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.object_reservations SET created_at=now()-interval '2 hours' WHERE source_id=:s"
            ),
            {"s": s},
        )
        conn.execute(
            text(
                "UPDATE app.objects SET created_at=now()-interval '2 hours' WHERE source_id=:s"
            ),
            {"s": s},
        )
    wait_sweep(runtime, objects, settings)
    with transaction(runtime, ids["alice"]) as conn:
        keys = (
            conn.execute(
                text("SELECT object_key FROM app.objects WHERE source_id=:s"), {"s": s}
            )
            .scalars()
            .all()
        )
        assert len(keys) > 2
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.object_reservations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
    for key in keys:
        objects.stat_object(settings.minio_bucket, key)
    # Simulate an aged folder removal for this disposable fixture only.
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE app.assets SET deleted=true WHERE source_id=:s"), {"s": s}
        )
        conn.execute(text("SET LOCAL session_replication_role='replica'"))
        conn.execute(
            text(
                "UPDATE app.assets SET deleted_at=now()-interval '2 hours' WHERE source_id=:s"
            ),
            {"s": s},
        )
    for _ in range(4):
        wait_sweep(runtime, objects, settings)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.media_presentations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.objects WHERE source_id=:s"), {"s": s}
            ).scalar_one()
            == 0
        )


def test_partial_retry_preserves_old_citations_and_switches_complete_set(
    foundation, tmp_path, monkeypatch
):
    from videomind.preprocessing.media import worker

    ids, owner, runtime, clients, *_ = foundation
    s, receipt, job, settings, objects = prepared(foundation, tmp_path)
    real = worker.run_extractor

    def partial(directory, progress):
        m = real(directory, progress)
        m["warnings"] = ["ASR_FAILED_TRACK_FIXTURE"]
        m["asr_status"] = "partial"
        return m

    monkeypatch.setattr(worker, "run_extractor", partial)
    process(runtime, objects, settings, job)
    base = f'/api/workspaces/{ids["workspace"]}/sources/{s}'
    r = receipt["revision_id"]
    alice = clients["alice"]
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT status FROM app.processing_runs WHERE id=:run"),
                {"run": job["processing_run_id"]},
            ).scalar_one()
            == "partial"
        )
    old = alice.get(f"{base}/revisions/{r}/media").json()
    assert old["manifest"]["partial"]
    citation = alice.get(f"{base}/revisions/{r}/media/segments").json()["items"][0][
        "citation_id"
    ]
    assert alice.post(f'{base}/jobs/{job["id"]}/retry').status_code == 202
    with owner.begin() as conn:
        new = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": job["workspace_id"], "s": s, "j": job["id"]},
        ).scalar_one()
    assert new
    monkeypatch.setattr(worker, "run_extractor", real)
    process(runtime, objects, settings, new)
    latest = alice.get(f"{base}/revisions/{r}/media").json()
    assert (
        latest["segment_set_id"] != old["segment_set_id"]
        and not latest["manifest"]["partial"]
    )
    assert (
        alice.get(f"{base}/citations/{citation}").json()["segment_set_id"]
        == old["segment_set_id"]
    )
    url = f'{base}/revisions/{r}/media/objects/{old["playback_object_id"]}?segment_set_id={old["segment_set_id"]}'
    assert alice.get(url, headers={"Range": "bytes=0-9"}).status_code == 206
