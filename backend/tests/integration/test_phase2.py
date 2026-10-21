"""Phase 2 release gates against real PostgreSQL/MinIO with disposable fixtures."""

import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import text

from test_foundation import foundation, insert, pytestmark
from videomind.config import Settings
from videomind.infrastructure.database import transaction
from videomind.infrastructure.services import object_client
from videomind.ingestion.service import ingest, finish
from videomind.ingestion.worker import validate
from videomind.assets.storage import sweep, STORAGE_LOCK


def wait_sweep(engine, objects, settings):
    # The real dispatcher can legitimately own the global maintenance lock.
    # Assert the completed batch rather than treating a safe skip as failure.
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = sweep(engine, objects, settings)
        if not result.get("busy"):
            return result
        time.sleep(0.05)
    pytest.fail("Maintenance lock did not become available")


def new_source(foundation):
    ids, owner, runtime, clients, *_ = foundation
    source = uuid4()
    with owner.begin() as conn:
        insert(
            conn,
            "app.sources",
            workspace_id=ids["workspace"],
            id=source,
            name="Phase2 fixture",
            connector_kind="upload",
            status="connected",
        )
    return source


def test_pagination_past_old_200_limit_and_scoped_cursors(foundation):
    ids, owner, runtime, clients, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    with owner.begin() as conn:
        for n in range(205):
            a, o, r = uuid4(), uuid4(), uuid4()
            scope = {"workspace_id": w, "source_id": s}
            insert(
                conn,
                "app.objects",
                **scope,
                id=o,
                bucket="videomind",
                object_key=f"pagination/{a}",
                sha256="d" * 64,
                size_bytes=1,
                mime_type="text/plain",
                role="original",
            )
            insert(
                conn,
                "app.assets",
                **scope,
                id=a,
                external_id=f"{n:03}",
                title=f"{n:03}.txt",
                modality="document",
                mime_type="text/plain",
                latest_revision_id=r,
            )
            insert(
                conn,
                "app.asset_revisions",
                **scope,
                id=r,
                asset_id=a,
                external_revision="v1",
                sha256="d" * 64,
                original_object_id=o,
            )
            insert(
                conn,
                "app.ingestion_jobs",
                **scope,
                kind="validate",
                revision_id=r,
                requested_by=ids["alice"],
                dedupe_key=str(r),
                trace_id=uuid4(),
                status="stored",
            )
    base = f"/api/workspaces/{w}/sources/{s}"
    alice = clients["alice"]
    all_ids = []
    cursor = ""
    while True:
        response = alice.get(
            base + "/assets",
            params={"limit": 50, **({"after": cursor} if cursor else {})},
        )
        assert (
            response.status_code == 200 and response.headers["x-total-count"] == "205"
        )
        all_ids.extend(i["id"] for i in response.json())
        cursor = response.headers["x-next-cursor"]
        if not cursor:
            break
    assert len(all_ids) == len(set(all_ids)) == 205
    jobs = []
    cursor = ""
    while True:
        response = alice.get(
            base + "/jobs",
            params={"limit": 50, **({"after": cursor} if cursor else {})},
        )
        jobs.extend(j["id"] for j in response.json())
        cursor = response.headers["x-next-cursor"]
        if not cursor:
            break
    assert len(jobs) == len(set(jobs)) == 205
    assert alice.get(base + "/assets", params={"limit": 201}).status_code == 422
    foreign = (
        f"/api/workspaces/{ids['other_workspace']}/sources/{ids['foreign']}/assets"
    )
    assert alice.get(foreign, params={"after": all_ids[0]}).status_code == 404
    assert clients["bob"].get(f"/api/workspaces/{w}/storage").status_code == 403
    assert alice.get(f"/api/workspaces/{w}/storage").status_code == 200


def test_quota_rejection_is_before_object_write_and_duplicate_is_noop(
    foundation, tmp_path
):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "notes.txt"
    path.write_text("quota fixture")
    result = ingest(
        runtime, objects, settings, ids["alice"], ids["workspace"], s, path, path.name
    )
    tiny = settings.model_copy(update={"workspace_storage_bytes": 1})
    # Identical bytes reuse the existing immutable original even at quota.
    assert ingest(
        runtime, objects, tiny, ids["alice"], ids["workspace"], s, path, path.name
    )["unchanged"]

    class NoWrite:
        def put_object(self, *args, **kwargs):
            raise AssertionError("quota must precede storage")

    path.write_text("new version")
    with pytest.raises(HTTPException) as error:
        ingest(
            runtime, NoWrite(), tiny, ids["alice"], ids["workspace"], s, path, path.name
        )
    assert error.value.status_code == 409
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": ids["workspace"], "s": s},
            ).scalar_one()
            == 1
        )


CHILD_INGEST = """
import json,os,signal,sys
from pathlib import Path
from uuid import UUID
from videomind.config import Settings
from videomind.infrastructure.database import database
from videomind.infrastructure.services import object_client
from videomind.ingestion.service import ingest
v=json.loads(sys.argv[1]);settings=Settings();engine=database(settings.database_url.get_secret_value());client=object_client(settings)
class Storage:
 def put_object(self,*args,**kwargs):
  if v['point']=='before_write':os.kill(os.getpid(),signal.SIGKILL)
  result=client.put_object(*args,**kwargs)
  if v['point']=='after_write':os.kill(os.getpid(),signal.SIGKILL)
  return result
result=ingest(engine,Storage(),settings,UUID(v['actor']),UUID(v['w']),UUID(v['s']),Path(v['path']),'crash.txt')
os.kill(os.getpid(),signal.SIGKILL)
"""


@pytest.mark.parametrize("point", ["before_write", "after_write", "after_commit"])
def test_sigkill_during_original_registration_converges(foundation, tmp_path, point):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "crash.txt"
    path.write_text("durable crash fixture")
    payload = {
        "point": point,
        "w": str(w),
        "s": str(s),
        "actor": str(ids["alice"]),
        "path": str(path),
    }
    result = subprocess.run(
        [sys.executable, "-c", CHILD_INGEST, json.dumps(payload)],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == -signal.SIGKILL
    with transaction(runtime, ids["alice"]) as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": s},
        ).scalar_one()
        assert count == (1 if point == "after_commit" else 0)
    recovered = ingest(
        runtime, objects, settings, ids["alice"], w, s, path, "crash.txt"
    )
    assert recovered["unchanged"] == (point == "after_commit")
    with transaction(runtime, ids["alice"]) as conn:
        for table in ("assets", "asset_revisions", "ingestion_jobs"):
            assert (
                conn.execute(
                    text(
                        f"SELECT count(*) FROM app.{table} WHERE workspace_id=:w AND source_id=:s"
                    ),
                    {"w": w, "s": s},
                ).scalar_one()
                == 1
            )
    # An interrupted successful object PUT is the only extra object. Its DB
    # transaction rolled back; the orphan sweeper must reclaim it, not the live original.
    keys = list(
        objects.list_objects(settings.minio_bucket, prefix=f"{w}/{s}/", recursive=True)
    )
    assert len(keys) == (2 if point == "after_write" else 1)
    with transaction(runtime, ids["alice"]) as conn:
        live = conn.execute(
            text(
                "SELECT object_key FROM app.objects WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": s},
        ).scalar_one()

    class Scope:
        def list_objects(self, *args, **kwargs):
            from datetime import datetime, timezone, timedelta

            return iter(
                SimpleNamespace(
                    object_name=i.object_name,
                    last_modified=datetime.now(timezone.utc) - timedelta(hours=2),
                )
                for i in keys
            )

        def remove_object(self, *args):
            return objects.remove_object(*args)

    swept = wait_sweep(runtime, Scope(), settings)
    assert swept["removed"] == (1 if point == "after_write" else 0)
    assert objects.stat_object(settings.minio_bucket, live).size == path.stat().st_size


CHILD_VALIDATE = """
import json,os,signal,sys
from sqlalchemy import text
from uuid import UUID
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
from videomind.infrastructure.services import object_client
from videomind.ingestion.service import finish
import videomind.ingestion.worker as worker
v=json.loads(sys.argv[1]);settings=Settings();engine=database(settings.database_url.get_secret_value());client=object_client(settings)
with transaction(engine,UUID(v['actor'])) as conn:
 conn.execute(text("UPDATE app.ingestion_jobs SET status='queued',available_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j"),v)
 job=conn.execute(text('SELECT app.intake_claim(:w,:s,:j)'),v).scalar_one()
 assert job
if v['point']=='after_claim':os.kill(os.getpid(),signal.SIGKILL)
original_run=worker.subprocess.run
if v['point'] in ('after_fetch','after_probe'):
 def run(*args,**kwargs):
  if v['point']=='after_fetch':os.kill(os.getpid(),signal.SIGKILL)
  result=original_run(*args,**kwargs)
  os.kill(os.getpid(),signal.SIGKILL)
 worker.subprocess.run=run
manifest=worker.validate(engine,client,settings,job)
assert finish(engine,job,'stored',manifest)
os.kill(os.getpid(),signal.SIGKILL)
"""


@pytest.mark.parametrize(
    "point", ["after_claim", "after_fetch", "after_probe", "after_finish"]
)
def test_sigkill_validation_attempts_recover_and_old_tokens_cannot_finish(
    foundation, tmp_path, point
):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "crash.txt"
    path.write_text("validation crash fixture")
    result = ingest(runtime, objects, settings, ids["alice"], w, s, path, path.name)
    payload = {
        "w": str(w),
        "s": str(s),
        "j": result["job_id"],
        "actor": str(ids["alice"]),
        "point": point,
    }
    # Make it unavailable to the live dispatcher until the child claims it atomically.
    with transaction(runtime, ids["alice"]) as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status='queued',available_at=now()+interval '1 day' WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            payload,
        )
    child = subprocess.run(
        [sys.executable, "-c", CHILD_VALIDATE, json.dumps(payload)],
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == -signal.SIGKILL
    with transaction(runtime, ids["alice"]) as conn:
        old = dict(
            conn.execute(
                text(
                    "SELECT * FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j"
                ),
                payload,
            )
            .mappings()
            .one()
        )
        if point == "after_finish":
            assert old["status"] == "stored"
            assert (
                conn.execute(
                    text("SELECT app.intake_claim(:w,:s,:j)"), payload
                ).scalar_one()
                is None
            )
            return
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            payload,
        )
        new = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"), payload
        ).scalar_one()
    assert new and new["lease_token"] != str(old["lease_token"])
    assert not finish(runtime, old, "stored", {"stale": True})
    assert finish(runtime, new, "stored", validate(runtime, objects, settings, new))
    assert not finish(runtime, new, "stored", {"duplicate": True})


def test_retention_removes_only_old_tombstones_and_preserves_live_bytes(
    foundation, tmp_path
):
    ids, owner, runtime, clients, *_ = foundation
    w = ids["workspace"]
    s = new_source(foundation)
    live_source = new_source(foundation)
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "retention.txt"
    path.write_text("retained immutable original")
    doomed = ingest(runtime, objects, settings, ids["alice"], w, s, path, path.name)
    live = ingest(
        runtime, objects, settings, ids["alice"], w, live_source, path, path.name
    )
    with transaction(runtime, ids["alice"]) as conn:
        doomed_key = conn.execute(
            text(
                "SELECT object_key FROM app.objects WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": s},
        ).scalar_one()
        live_key = conn.execute(
            text(
                "SELECT object_key FROM app.objects WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": live_source},
        ).scalar_one()
    assert (
        clients["alice"].delete(f"/api/workspaces/{w}/sources/{s}").status_code == 204
    )
    # A fresh tombstone must survive maintenance's one-hour floor.
    with runtime.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": STORAGE_LOCK})
        conn.execute(text("SELECT app.retire_intake()"))
    with owner.connect() as conn:
        assert conn.execute(
            text("SELECT id FROM app.sources WHERE workspace_id=:w AND id=:s"),
            {"w": w, "s": s},
        ).first()
    # Advance only this fixture's deletion age, without waiting an hour or
    # lowering the production retention floor. The owner can set fixture ages.
    with owner.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role='replica'"))
        conn.execute(
            text(
                "UPDATE app.sources SET deleted_at=now()-interval '2 hours' WHERE workspace_id=:w AND id=:s"
            ),
            {"w": w, "s": s},
        )

    class FixtureInventory:
        def list_objects(self, *args, **kwargs):
            from datetime import datetime, timezone, timedelta

            return iter(
                SimpleNamespace(
                    object_name=k,
                    last_modified=datetime.now(timezone.utc) - timedelta(hours=2),
                )
                for k in (doomed_key, live_key)
            )

        def remove_object(self, *args):
            return objects.remove_object(*args)

    assert wait_sweep(runtime, FixtureInventory(), settings)["removed"] == 1
    with owner.connect() as conn:
        assert not conn.execute(
            text("SELECT id FROM app.sources WHERE workspace_id=:w AND id=:s"),
            {"w": w, "s": s},
        ).first()
    with runtime.begin() as conn:
        assert (
            conn.execute(
                text("SELECT app.intake_claim(:w,:s,:j)"),
                {"w": w, "s": s, "j": doomed["job_id"]},
            ).scalar_one()
            is None
        )
    with pytest.raises(HTTPException) as error:
        ingest(runtime, objects, settings, ids["alice"], w, s, path, path.name)
    assert error.value.status_code == 404
    download = objects.get_object(settings.minio_bucket, live_key)
    try:
        assert download.read() == path.read_bytes()
    finally:
        download.close()
        download.release_conn()


def test_active_writer_excludes_gc_and_failed_put_reservations_remain_charged(
    foundation, tmp_path
):
    from sqlalchemy import create_engine
    from videomind.assets.storage import lock_writer

    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    settings = Settings()
    path = tmp_path / "pending.txt"
    path.write_text("reservation bytes")

    class Unavailable:
        def put_object(self, *args, **kwargs):
            raise RuntimeError("fixture storage unavailable")

    with pytest.raises(RuntimeError):
        ingest(
            runtime,
            Unavailable(),
            settings,
            ids["alice"],
            ids["workspace"],
            s,
            path,
            path.name,
        )
    with transaction(runtime, ids["alice"]) as conn:
        pending = conn.execute(
            text(
                "SELECT object_key,size_bytes FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": ids["workspace"], "s": s},
        ).one()
        assert pending.size_bytes == path.stat().st_size
        assert not conn.execute(
            text("SELECT app.storage_admit(:w,:s,1,1,1)"),
            {"w": ids["workspace"], "s": s},
        ).scalar_one()
    other = create_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    try:
        with transaction(runtime, ids["alice"]) as conn:
            lock_writer(conn, ids["workspace"])
            assert sweep(other, Unavailable(), settings) == {"busy": True}
    finally:
        other.dispose()
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.object_reservations SET created_at=now()-interval '2 hours' WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": ids["workspace"], "s": s},
        )

    class EmptyInventory:
        def list_objects(self, *args, **kwargs):
            return iter(())

        def remove_object(self, bucket, key):
            assert key == pending.object_key

    wait_sweep(runtime, EmptyInventory(), settings)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": ids["workspace"], "s": s},
            ).scalar_one()
            == 0
        )


def test_full_scan_cursor_advances_only_after_success_and_deletions_reconcile(
    foundation, tmp_path, monkeypatch
):
    from videomind.ingestion.worker import sync_folder
    from videomind.connectors.local_folder.adapter import LocalFolderConnector
    from videomind.connectors.upload.validation import InvalidFile

    ids, owner, runtime, *_ = foundation
    w = ids["workspace"]
    s = new_source(foundation)
    settings = Settings().model_copy(update={"import_root": str(tmp_path)})
    objects = object_client(settings)
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.sources SET connector_kind='local_folder',config='{"
                + '"folder":""'
                + "}'::jsonb WHERE workspace_id=:w AND id=:s"
            ),
            {"w": w, "s": s},
        )
    (tmp_path / "a.txt").write_text("first")
    (tmp_path / "b.txt").write_text("keep until complete scan")

    def claim():
        with transaction(runtime, ids["alice"]) as conn:
            j = uuid4()
            v = {"w": w, "s": s, "j": j, "p": ids["alice"], "trace": uuid4()}
            conn.execute(
                text(
                    "INSERT INTO app.ingestion_jobs(workspace_id,source_id,id,kind,requested_by,dedupe_key,trace_id) VALUES (:w,:s,:j,'folder_sync',:p,CAST(:j AS text),:trace)"
                ),
                v,
            )
            return conn.execute(
                text("SELECT app.intake_claim(:w,:s,:j)"), v
            ).scalar_one()

    def cursor():
        with transaction(runtime, ids["alice"]) as conn:
            return conn.execute(
                text(
                    "SELECT sync_cursor FROM app.sources WHERE workspace_id=:w AND id=:s"
                ),
                {"w": w, "s": s},
            ).scalar_one()

    first = claim()
    manifest = sync_folder(runtime, objects, settings, first)
    assert finish(runtime, first, "stored", manifest)
    old_cursor = cursor()
    assert old_cursor and manifest["files_seen"] == 2
    (tmp_path / "a.txt").write_text("changed")
    (tmp_path / "b.txt").unlink()
    (tmp_path / "c.txt").write_text("new")
    original = LocalFolderConnector.fetch

    async def interrupted(self, item):
        if item.external_id == "c.txt":
            raise InvalidFile("FIXTURE_FETCH_FAILURE")
        async for chunk in original(self, item):
            yield chunk

    monkeypatch.setattr(LocalFolderConnector, "fetch", interrupted)
    second = claim()
    with pytest.raises(InvalidFile):
        sync_folder(runtime, objects, settings, second)
    assert finish(runtime, second, "failed", error="FIXTURE_FETCH_FAILURE")
    assert cursor() == old_cursor
    with transaction(runtime, ids["alice"]) as conn:
        progress = conn.execute(
            text(
                "SELECT manifest FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            {"w": w, "s": s, "j": second["id"]},
        ).scalar_one()
        assert progress["files_seen"] == 1 and progress["files_expected"] == 2
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.assets WHERE workspace_id=:w AND source_id=:s AND NOT deleted"
                ),
                {"w": w, "s": s},
            ).scalar_one()
            == 2
        )
    monkeypatch.setattr(LocalFolderConnector, "fetch", original)
    third = claim()
    manifest = sync_folder(runtime, objects, settings, third)
    assert finish(runtime, third, "stored", manifest)
    assert (
        cursor() != old_cursor
        and manifest["deleted"] == 1
        and manifest["unchanged"] == 1
    )

    # Retire a removed folder item without discarding live revision history.
    with owner.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role='replica'"))
        conn.execute(
            text(
                "UPDATE app.assets SET deleted_at=now()-interval '2 hours' WHERE workspace_id=:w AND source_id=:s AND external_id='b.txt'"
            ),
            {"w": w, "s": s},
        )
        conn.execute(
            text(
                "UPDATE app.objects SET created_at=now()-interval '2 hours' WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": w, "s": s},
        )
    with runtime.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": STORAGE_LOCK})
        conn.execute(text("SELECT app.retire_intake()"))
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.assets WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": w, "s": s},
            ).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": w, "s": s},
            ).scalar_one()
            == 3
        )


def test_lost_broker_delivery_is_reconstructed_from_postgres(
    foundation, monkeypatch, tmp_path
):
    from celery import Celery
    from videomind.infrastructure.services import redis_client
    import videomind.ingestion.dispatcher as dispatcher
    from test_foundation import wait_intake
    from sqlalchemy import create_engine

    ids, owner, runtime, clients, *_ = foundation
    s = new_source(foundation)
    settings = Settings()
    w = ids["workspace"]
    path = tmp_path / "broker.txt"
    path.write_text("recover after lost delivery")
    result = ingest(
        runtime, object_client(settings), settings, ids["alice"], w, s, path, path.name
    )
    queue = "phase2-verify-" + uuid4().hex
    testapp = Celery("phase2-verify", broker=settings.redis_url.get_secret_value())
    testapp.conf.task_default_queue = queue
    monkeypatch.setattr(dispatcher, "app", testapp)
    redis = redis_client(settings)
    other = create_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    try:
        # Lock this disposable row against the live worker while exercising real
        # delivery loss. Only this uniquely named fixture queue is deleted.
        with transaction(runtime, ids["alice"]) as conn:
            conn.execute(
                text(
                    "UPDATE app.ingestion_jobs SET status='queued',available_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j"
                ),
                {"w": w, "s": s, "j": result["job_id"]},
            )
        with transaction(runtime, ids["alice"]) as conn:
            conn.execute(
                text(
                    "SELECT id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j FOR UPDATE"
                ),
                {"w": w, "s": s, "j": result["job_id"]},
            )
            dispatcher.tick(other)
            assert redis.llen(queue) > 0
            redis.delete(queue)
            assert redis.llen(queue) == 0
            dispatcher.tick(other)
            assert redis.llen(queue) > 0
        assert (
            wait_intake(
                clients["alice"], f"/api/workspaces/{w}/sources/{s}", result["job_id"]
            )["status"]
            == "stored"
        )
    finally:
        redis.delete(queue)
        redis.close()
        testapp.close()
        other.dispose()


def test_exhausted_attempts_close_stages_and_manual_retry_recovers(
    foundation, tmp_path
):
    from test_foundation import wait_intake

    ids, owner, runtime, clients, *_ = foundation
    w = ids["workspace"]
    s = new_source(foundation)
    settings = Settings()
    path = tmp_path / "retry.txt"
    path.write_text("retry original")
    accepted = ingest(
        runtime, object_client(settings), settings, ids["alice"], w, s, path, path.name
    )
    v = {"w": w, "s": s, "j": accepted["job_id"]}
    with transaction(runtime, ids["alice"]) as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status='running',attempt=3,lease_expires_at=now()-interval '1 second' WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            v,
        )
        assert (
            conn.execute(text("SELECT app.intake_claim(:w,:s,:j)"), v).scalar_one()
            is None
        )
        assert (
            conn.execute(
                text(
                    "SELECT status FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND id=:j"
                ),
                v,
            ).scalar_one()
            == "failed"
        )
        assert (
            conn.execute(
                text(
                    "SELECT status FROM app.stage_runs WHERE workspace_id=:w AND source_id=:s AND stage='validate_original'"
                ),
                v,
            ).scalar_one()
            == "failed"
        )
        assert (
            conn.execute(
                text(
                    "SELECT status FROM app.processing_runs WHERE workspace_id=:w AND source_id=:s AND profile_hash='c57d9fd8284c2218387be2e45f4b853d59959ce33e4a737427375778f5237a95'"
                ),
                v,
            ).scalar_one()
            == "failed"
        )
    base = f"/api/workspaces/{w}/sources/{s}"
    assert (
        clients["alice"].post(base + f"/jobs/{accepted['job_id']}/retry").status_code
        == 202
    )
    assert wait_intake(clients["alice"], base, accepted["job_id"])["status"] == "stored"
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT status FROM app.stage_runs WHERE workspace_id=:w AND source_id=:s AND stage='validate_original'"
                ),
                v,
            ).scalar_one()
            == "stored"
        )
        assert (
            conn.execute(
                text(
                    "SELECT status FROM app.processing_runs WHERE workspace_id=:w AND source_id=:s AND profile_hash='c57d9fd8284c2218387be2e45f4b853d59959ce33e4a737427375778f5237a95'"
                ),
                v,
            ).scalar_one()
            == "ready"
        )


def test_bounded_original_uses_atomic_put_without_durable_multipart_parts(
    foundation, tmp_path, monkeypatch
):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "single-put.txt"
    path.write_bytes(b"A" * (7 * 1024**2))

    def multipart_forbidden(*args, **kwargs):
        raise AssertionError("bounded originals must not leave durable multipart state")

    monkeypatch.setattr(objects, "_create_multipart_upload", multipart_forbidden)
    result = ingest(
        runtime, objects, settings, ids["alice"], ids["workspace"], s, path, path.name
    )
    with transaction(runtime, ids["alice"]) as conn:
        key = conn.execute(
            text(
                "SELECT object_key FROM app.objects WHERE workspace_id=:w AND source_id=:s"
            ),
            {"w": ids["workspace"], "s": s},
        ).scalar_one()
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": ids["workspace"], "s": s},
            ).scalar_one()
            == 0
        )
    assert (
        result["status"] == "queued"
        and objects.stat_object(settings.minio_bucket, key).size == path.stat().st_size
    )


def test_upload_size_limit_rejects_declared_and_chunked_overflow_before_storage(
    foundation,
):
    import http.client

    ids, owner, runtime, clients, *_ = foundation
    w = ids["workspace"]
    s = new_source(foundation)
    alice = clients["alice"]
    base = f"/api/workspaces/{w}/sources/{s}"
    connection = http.client.HTTPConnection("api", 8000, timeout=10)
    try:
        connection.putrequest("POST", base + "/files?filename_value=too-big.txt")
        connection.putheader(
            "Cookie", "; ".join(f"{k}={v}" for k, v in alice.cookies.items())
        )
        connection.putheader("Content-Length", str(64 * 1024**2 + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        response.read()
    finally:
        connection.close()
    response = alice.post(
        base + "/files",
        params={"filename_value": "chunked-overflow.txt"},
        content=(b"x" * 1024**2 for _ in range(65)),
        timeout=30,
    )
    assert response.status_code == 413
    with transaction(runtime, ids["alice"]) as conn:
        for table in ("assets", "object_reservations", "ingestion_jobs"):
            assert (
                conn.execute(
                    text(
                        f"SELECT count(*) FROM app.{table} WHERE workspace_id=:w AND source_id=:s"
                    ),
                    {"w": w, "s": s},
                ).scalar_one()
                == 0
            )
