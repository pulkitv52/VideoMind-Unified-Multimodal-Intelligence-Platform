"""Document evidence, fencing, quotas and revocation on the deployed runtime role."""

import json
from pathlib import Path
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from test_foundation import foundation, insert, pytestmark
from test_phase2 import new_source, wait_sweep
from document_fixtures import make_pdf
from videomind.config import Settings
from videomind.connectors.upload.validation import InvalidFile
from videomind.infrastructure.database import transaction
from videomind.infrastructure.services import object_client
from videomind.ingestion.service import ingest
from videomind.preprocessing.documents.worker import process


def prepared_job(
    foundation,
    tmp_path,
    data=b"Immutable document evidence with a Unicode cafe.\r\nSecond line.",
):
    ids, owner, runtime, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    settings = Settings()
    objects = object_client(settings)
    path = tmp_path / "input"
    path.write_bytes(data)
    receipt = ingest(
        runtime, objects, settings, ids["alice"], w, s, path, "document.txt"
    )
    # Hold validation and auto-enqueue inside the same transaction: the live
    # dispatcher never sees an unclaimed fixture document receipt.
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status='stored' WHERE workspace_id=:w AND source_id=:s AND id=:j"
            ),
            {"w": w, "s": s, "j": receipt["job_id"]},
        )
        row = conn.execute(
            text(
                "SELECT id FROM app.ingestion_jobs WHERE workspace_id=:w AND source_id=:s AND revision_id=:r AND kind='document' FOR UPDATE"
            ),
            {"w": w, "s": s, "r": receipt["revision_id"]},
        ).scalar_one()
        job = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"), {"w": w, "s": s, "j": row}
        ).scalar_one()
    assert job
    return s, receipt, job, settings, objects


def test_atomic_document_output_and_unicode_citations_remain_on_old_revision(
    foundation, tmp_path
):
    ids, owner, runtime, clients, *_ = foundation
    original = "## Emergency\r\n\r\nCafé 😀 safety procedure.\r\nClose the pump.\r\n"
    s, receipt, job, settings, objects = prepared_job(
        foundation, tmp_path, original.encode()
    )
    process(runtime, objects, settings, job)
    base = f'/api/workspaces/{ids["workspace"]}/sources/{s}'
    r = receipt["revision_id"]
    alice = clients["alice"]
    bob = clients["bob"]
    descriptor = alice.get(f"{base}/revisions/{r}/document")
    assert (
        descriptor.status_code == 200
        and descriptor.json()["manifest"]["search_inputs_ready"]
    )
    page = alice.get(f"{base}/revisions/{r}/document/pages/1").json()
    segment = next(
        s for s in page["segments"] if s["text_content"] and "Café" in s["text_content"]
    )
    assert (
        original[segment["start_char"] : segment["end_char"]] == segment["text_content"]
    )
    citation = f'{base}/citations/{segment["citation_id"]}'
    resolved = alice.get(citation).json()
    assert (
        resolved["revision_id"] == r and resolved["offset_unit"] == "Unicode code point"
    )
    artifact = f'{base}/revisions/{r}/document/objects/{page["text_object_id"]}'
    assert alice.get(artifact).content == original.encode()
    assert bob.get(citation).status_code == bob.get(artifact).status_code == 404
    unknown = alice.get(f"{base}/revisions/{r}/document/objects/{uuid4()}")
    assert unknown.status_code == 404
    newer = alice.post(
        base + "/files",
        params={"filename_value": "document.txt"},
        content=b"Changed document, new immutable revision.",
    ).json()
    assert newer["revision_id"] != r
    assert alice.get(citation).json()["revision_id"] == r
    assert alice.get(f"{base}/revisions/{r}/original").content == original.encode()
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.embeddings WHERE source_id=:s"), {"s": s}
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.searchable_text WHERE source_id=:s AND lexemes @@ plainto_tsquery('simple','safety')"
                ),
                {"s": s},
            ).scalar_one()
            > 0
        )
    with pytest.raises(InvalidFile, match="LEASE_EXPIRED"):
        process(runtime, objects, settings, job)
    with owner.begin() as conn:
        insert(
            conn,
            "app.source_grants",
            workspace_id=ids["workspace"],
            source_id=s,
            principal_id=ids["bob"],
            permission="read",
        )
    assert bob.get(citation).status_code == bob.get(artifact).status_code == 200
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": s})
    for url in (
        citation,
        artifact,
        f"{base}/revisions/{r}/document",
        f"{base}/revisions/{r}/document/pages/1",
        f"{base}/revisions/{r}/original",
    ):
        assert bob.get(url).status_code == 404
    assert alice.delete(base).status_code == 204
    assert alice.get(citation).status_code == alice.get(artifact).status_code == 404


def test_stale_document_lease_cannot_publish_and_retry_has_one_complete_set(
    foundation, tmp_path
):
    ids, owner, runtime, *_ = foundation
    s, receipt, old, settings, objects = prepared_job(foundation, tmp_path)
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": old["id"]},
        )
        new = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": old["workspace_id"], "s": s, "j": old["id"]},
        ).scalar_one()
    with pytest.raises(InvalidFile, match="LEASE_EXPIRED"):
        process(runtime, objects, settings, old)
    process(runtime, objects, settings, new)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.segment_sets WHERE source_id=:s AND status='ready'"
                ),
                {"s": s},
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.object_reservations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT status FROM app.stage_runs WHERE processing_run_id=:run"),
                {"run": new["processing_run_id"]},
            ).scalar_one()
            == "stored"
        )


def test_document_quota_failure_is_atomic_and_retention_reclaims_derivatives(
    foundation, tmp_path
):
    ids, owner, runtime, clients, *_ = foundation
    s, receipt, job, settings, objects = prepared_job(foundation, tmp_path)

    limited = settings.model_copy(update={"workspace_storage_bytes": 1})
    with pytest.raises(InvalidFile, match="DOCUMENT_STORAGE_LIMIT"):
        process(runtime, objects, limited, job)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.segment_sets WHERE source_id=:s"),
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
    with transaction(runtime, ids["alice"]) as conn:
        keys = (
            conn.execute(
                text("SELECT object_key FROM app.objects WHERE source_id=:s"), {"s": s}
            )
            .scalars()
            .all()
        )
        assert len(keys) > 1
    # Remove only this fixture asset, as a completed folder scan would do.
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
        conn.execute(
            text(
                "UPDATE app.objects SET created_at=now()-interval '2 hours' WHERE source_id=:s"
            ),
            {"s": s},
        )
    wait_sweep(runtime, objects, settings)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.document_pages WHERE source_id=:s"),
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
    # Physical object inventory ages independently; reference retirement is verified here.


def test_pdf_page_images_tiles_and_citation_bounds_are_authorized(foundation, tmp_path):
    ids, owner, runtime, clients, *_ = foundation
    s = new_source(foundation)
    w = ids["workspace"]
    alice = clients["alice"]
    bob = clients["bob"]
    path = make_pdf(
        tmp_path / "original",
        [
            {
                "lines": [(50, 740, "Safety checklist and equipment procedure")],
                "scan": "Inspect the pump daily.",
            }
        ],
    )
    base = f"/api/workspaces/{w}/sources/{s}"
    receipt = alice.post(
        base + "/files",
        params={"filename_value": "mixed.pdf"},
        content=path.read_bytes(),
    ).json()
    deadline = time.monotonic() + 90
    asset = None
    while time.monotonic() < deadline:
        rows = alice.get(base + "/assets").json()
        asset = rows[0] if rows else None
        if (
            asset
            and asset["document"]
            and asset["document"]["status"] in ("stored", "failed")
        ):
            break
        time.sleep(0.2)
    assert asset and asset["document"]["status"] == "stored", asset
    r = receipt["revision_id"]
    page = alice.get(f"{base}/revisions/{r}/document/pages/1").json()
    assert any(s["representation"] == "ocr" for s in page["segments"])
    assert sum(s["representation"] == "image" for s in page["segments"]) > 1
    for segment in page["segments"]:
        box = segment["transform"]["box"]
        assert 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
        url = f'{base}/citations/{segment["citation_id"]}'
        resolved = alice.get(url)
        assert (
            resolved.status_code == 200
            and resolved.json()["revision_id"] == r
            and resolved.json()["page"] == 1
        )
        assert bob.get(url).status_code == 404
    image = f'{base}/revisions/{r}/document/objects/{page["image_object_id"]}'
    response = alice.get(image)
    assert (
        response.status_code == 200
        and response.headers["content-type"] == "image/png"
        and response.content.startswith(b"\x89PNG")
    )
    assert bob.get(image).status_code == 404
    assert alice.delete(base).status_code == 204
    assert alice.get(image).status_code == 404


def test_killed_document_writer_leaves_no_partial_evidence_and_recovers(
    foundation, tmp_path
):
    import os, signal, subprocess, sys

    ids, owner, runtime, *_ = foundation
    s, receipt, job, settings, objects = prepared_job(foundation, tmp_path)
    fixture = tmp_path / "document-job.json"
    fixture.write_text(json.dumps(job))
    script = """
import json,os,signal,sys
from videomind.config import Settings
from videomind.infrastructure.database import database
from videomind.infrastructure.services import object_client
from videomind.preprocessing.documents.worker import process
settings=Settings();engine=database(settings.database_url.get_secret_value());client=object_client(settings)
class KillAfterPut:
 def __getattr__(self,name): return getattr(client,name)
 def put_object(self,*args,**kwargs):
  result=client.put_object(*args,**kwargs)
  os.kill(os.getpid(),signal.SIGKILL)
process(engine,KillAfterPut(),settings,json.load(open(sys.argv[1])))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(fixture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    assert child.returncode == -signal.SIGKILL
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.segment_sets WHERE source_id=:s"),
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
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.objects WHERE source_id=:s AND role='derivative'"
                ),
                {"s": s},
            ).scalar_one()
            == 0
        )
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:j"
            ),
            {"j": job["id"]},
        )
        recovered = conn.execute(
            text("SELECT app.intake_claim(:w,:s,:j)"),
            {"w": job["workspace_id"], "s": s, "j": job["id"]},
        ).scalar_one()
    process(runtime, objects, settings, recovered)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.segment_sets WHERE source_id=:s AND status='ready'"
                ),
                {"s": s},
            ).scalar_one()
            == 1
        )
    # Aged reservation cleanup removes only the failed attempt, preserving live output.
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE app.object_reservations SET created_at=now()-interval '2 hours' WHERE source_id=:s"
            ),
            {"s": s},
        )
    wait_sweep(runtime, objects, settings)
    with transaction(runtime, ids["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.object_reservations WHERE source_id=:s"),
                {"s": s},
            ).scalar_one()
            == 0
        )
        live = (
            conn.execute(
                text("SELECT object_key FROM app.objects WHERE source_id=:s"), {"s": s}
            )
            .scalars()
            .all()
        )
    for key in live:
        assert objects.stat_object(settings.minio_bucket, key).size > 0


def test_encrypted_pdf_reports_actionable_error_and_preserves_original(
    foundation, tmp_path
):
    from pypdf import PdfWriter
    from test_foundation import wait_intake

    ids, owner, runtime, clients, *_ = foundation
    s = new_source(foundation)
    base = f'/api/workspaces/{ids["workspace"]}/sources/{s}'
    writer = PdfWriter()
    writer.add_blank_page(600, 800)
    writer.encrypt("fixture password")
    path = tmp_path / "encrypted.pdf"
    writer.write(path)
    receipt = (
        clients["alice"]
        .post(
            base + "/files",
            params={"filename_value": "encrypted.pdf"},
            content=path.read_bytes(),
        )
        .json()
    )
    result = wait_intake(clients["alice"], base, receipt["job_id"])
    assert result["status"] == "failed" and result["error_code"] == "DOCUMENT_ENCRYPTED"
    assert (
        clients["alice"].get(f'{base}/assets/{receipt["asset_id"]}/original').content
        == path.read_bytes()
    )
