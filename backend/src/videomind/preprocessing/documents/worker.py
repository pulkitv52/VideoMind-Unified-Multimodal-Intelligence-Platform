"""Durable document work with fenced, all-or-nothing evidence publication."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from videomind.assets.storage import admit, lock_writer
from videomind.connectors.upload.validation import InvalidFile
from videomind.infrastructure.database import transaction
from videomind.ingestion.service import digest, source_scope
from videomind.ingestion.jobs import scope, fence
from .profile import CONFIG, PROFILE
from .contracts import validate_manifest


def run_extractor(directory, mime, progress=None):
    # Never inherit DB credentials or other service secrets into a parser.
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "XDG_CACHE_HOME": str(directory / "cache"),
        "XDG_RUNTIME_DIR": str(directory),
        "LANG": "C.UTF-8",
        "OMP_THREAD_LIMIT": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "SAL_USE_VCLPLUGIN": "svp",
        "OSL_SOCKET_PATH": str(directory),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "videomind.preprocessing.documents.extract",
            str(directory),
            mime,
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + CONFIG["wall_seconds"]
    last = {"stage": "extract", "pages_done": 0}
    checked = 0.0
    try:
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise InvalidFile("DOCUMENT_TIMEOUT")
            path = directory / "progress.json"
            if progress and path.exists():
                try:
                    data = json.loads(path.read_text())
                except (ValueError, OSError):
                    data = None
                if data is not None:
                    last = data
            if progress and time.monotonic() - checked >= 2:
                progress(last)
                checked = time.monotonic()
            time.sleep(0.2)
        result_path = directory / "result.json"
        if not result_path.exists() or result_path.stat().st_size > 32 * 1024**2:
            raise InvalidFile("DOCUMENT_RESOURCE_LIMIT")
        result = json.loads(result_path.read_text())
        if not result["ok"]:
            raise InvalidFile(result["error_code"])
        if result["manifest"]["profile"] != PROFILE:
            raise InvalidFile("DOCUMENT_PROFILE_MISMATCH")
        return validate_manifest(result["manifest"], directory)
    finally:
        # The process group includes any remaining renderer children.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def artifact_files(manifest):
    files = {}
    for page in manifest["pages"]:
        files[page["text_file"]] = "text/plain; charset=utf-8"
        if page["image_file"]:
            files[page["image_file"]] = "image/png"
        for tile in page["tiles"]:
            files[tile["file"]] = "image/png"
    if manifest["rendering_file"]:
        files[manifest["rendering_file"]] = "application/pdf"
    if manifest["structure_file"]:
        files[manifest["structure_file"]] = "application/json"
    return files


def publish(engine, objects, settings, job, original, directory, manifest):
    actor = UUID(str(job["requested_by"]))
    v = scope(job)
    artifacts = {}
    for name, mime in artifact_files(manifest).items():
        if Path(name).name != name:
            raise InvalidFile("DOCUMENT_MANIFEST_INVALID")
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise InvalidFile("DOCUMENT_MANIFEST_INVALID")
        oid = uuid4()
        artifacts[name] = {
            "id": oid,
            "key": f"{v['w']}/{v['s']}/documents/{oid}/{digest(path)}",
            "sha": digest(path),
            "size": path.stat().st_size,
            "mime": mime,
            "path": path,
        }
    if sum(a["size"] for a in artifacts.values()) > CONFIG["max_output_bytes"]:
        raise InvalidFile("DOCUMENT_OUTPUT_LIMIT")
    # Durable reservations survive a killed writer and count against workspace quotas.
    with transaction(engine, actor) as conn:
        lock_writer(conn, v["w"])
        source_scope(conn, v["w"], v["s"], write=True)
        fence(conn, v)
        for a in artifacts.values():
            admit(conn, settings, v["w"], v["s"], a["size"])
            conn.execute(
                text(
                    "INSERT INTO app.object_reservations(workspace_id,source_id,id,bucket,object_key,size_bytes) VALUES (:w,:s,:i,:b,:k,:size)"
                ),
                dict(v, i=a["id"], b=settings.minio_bucket, k=a["key"], size=a["size"]),
            )
    with transaction(engine, actor) as conn:
        lock_writer(conn, v["w"])
        source_scope(conn, v["w"], v["s"], write=True, lock=True)
        fence(conn, v, lock=True)
        # Deleted folder assets must not acquire new published document evidence.
        if not conn.execute(
            text(
                "SELECT id FROM app.assets WHERE workspace_id=:w AND source_id=:s AND id=:a AND NOT deleted"
            ),
            dict(v, a=original["asset_id"]),
        ).first():
            raise InvalidFile("SOURCE_UNAVAILABLE")
        for a in artifacts.values():
            if not conn.execute(
                text(
                    "SELECT id FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s AND id=:i"
                ),
                dict(v, i=a["id"]),
            ).first():
                raise InvalidFile("DOCUMENT_RESERVATION_EXPIRED")
            with a["path"].open("rb") as stream:
                objects.put_object(
                    settings.minio_bucket,
                    a["key"],
                    stream,
                    a["size"],
                    content_type=a["mime"],
                    part_size=max(settings.max_upload_bytes, 5 * 1024**2),
                    num_parallel_uploads=1,
                )
            conn.execute(
                text(
                    "INSERT INTO app.objects(workspace_id,source_id,id,bucket,object_key,sha256,size_bytes,mime_type,role,derived_from_id) VALUES (:w,:s,:i,:b,:k,:sha,:size,:mime,'derivative',:original)"
                ),
                dict(
                    v,
                    i=a["id"],
                    b=settings.minio_bucket,
                    k=a["key"],
                    sha=a["sha"],
                    size=a["size"],
                    mime=a["mime"],
                    original=original["original_object_id"],
                ),
            )
            conn.execute(
                text(
                    "DELETE FROM app.object_reservations WHERE workspace_id=:w AND source_id=:s AND id=:i"
                ),
                dict(v, i=a["id"]),
            )
        sid = uuid4()
        v["set"] = sid
        rendering = (
            artifacts[manifest["rendering_file"]]["id"]
            if manifest["rendering_file"]
            else None
        )
        summary = {
            "profile": PROFILE,
            "configuration": CONFIG,
            "page_count": len(manifest["pages"]),
            "warnings": manifest["warnings"],
            "rendering_object_id": str(rendering) if rendering else None,
            "structure_object_id": (
                str(artifacts[manifest["structure_file"]]["id"])
                if manifest["structure_file"]
                else None
            ),
            "producer": "documents-v1",
            "runtime_packages_sha256": digest(
                Path("/usr/share/videomind-packages.txt")
            ),
            "searchable": False,
            "search_inputs_ready": True,
            "ocr_pages": sum(p["ocr"] for p in manifest["pages"]),
        }
        conn.execute(
            text(
                "INSERT INTO app.segment_sets(workspace_id,source_id,id,revision_id,processing_run_id,segmenter_profile,status,manifest) VALUES (:w,:s,:set,:r,:run,:profile,'building',CAST(:manifest AS jsonb))"
            ),
            dict(v, profile=PROFILE, manifest=json.dumps(summary)),
        )
        ordinal = 0
        for page in manifest["pages"]:
            text_id = artifacts[page["text_file"]]["id"]
            image_id = (
                artifacts[page["image_file"]]["id"] if page["image_file"] else None
            )
            conn.execute(
                text(
                    "INSERT INTO app.document_pages(workspace_id,source_id,segment_set_id,revision_id,page,text_object_id,image_object_id,rendering_object_id,width,height,manifest) VALUES (:w,:s,:set,:r,:page,:text,:image,:render,:width,:height,CAST(:manifest AS jsonb))"
                ),
                dict(
                    v,
                    page=page["page"],
                    text=text_id,
                    image=image_id,
                    render=rendering,
                    width=page["width"],
                    height=page["height"],
                    manifest=json.dumps(
                        {
                            "lines": page["lines"],
                            "ocr": page["ocr"],
                            "offset_unit": "Unicode code point",
                            "origin": "rendered_docx" if rendering else "original",
                        }
                    ),
                ),
            )
            entries = [
                dict(
                    c,
                    representation="ocr" if c["method"] == "ocr" else "text",
                    derived=None,
                )
                for c in page["chunks"]
            ]
            if image_id:
                entries.append(
                    {
                        "representation": "image",
                        "derived": image_id,
                        "box": [0, 0, 1, 1],
                        "method": "page_image",
                        "text": None,
                    }
                )
            entries.extend(
                {
                    "representation": "image",
                    "derived": artifacts[t["file"]]["id"],
                    "box": t["box"],
                    "method": "page_tile",
                    "text": None,
                }
                for t in page["tiles"]
            )
            for entry in entries:
                segment, anchor, citation = uuid4(), uuid4(), uuid4()
                transform = {
                    "box": entry.get("box"),
                    "coordinate_space": "display-page-normalized-top-left",
                    "rendering_object_id": str(rendering) if rendering else None,
                    "profile": PROFILE,
                    "text_start": entry.get("start"),
                    "text_end": entry.get("end"),
                    "text_object_id": str(text_id),
                    "structure": entry.get("structure"),
                    "rotation_applied": True,
                }
                params = dict(
                    v,
                    seg=segment,
                    anchor=anchor,
                    citation=citation,
                    rep=entry["representation"],
                    ordinal=ordinal,
                    content=entry.get("text"),
                    derived=entry["derived"],
                    quality=json.dumps(
                        {"method": entry["method"], "confidence_calibrated": False}
                    ),
                    original=original["original_object_id"],
                    transform=json.dumps(transform),
                    page=page["page"] if image_id else None,
                    text_obj=None if image_id else text_id,
                    start=None if image_id else entry["start"],
                    end=None if image_id else entry["end"],
                    kind="page" if image_id else "text",
                    relation=(
                        "depicts"
                        if entry["representation"] == "image"
                        else (
                            "ocr_from"
                            if entry["representation"] == "ocr"
                            else "extracted_from"
                        )
                    ),
                )
                conn.execute(
                    text(
                        "INSERT INTO app.segments(workspace_id,source_id,id,segment_set_id,revision_id,representation,ordinal,text_content,language,producer,quality,derived_object_id) VALUES (:w,:s,:seg,:set,:r,:rep,:ordinal,:content,CASE WHEN :rep='ocr' THEN 'en' ELSE NULL END,'documents-v1',CAST(:quality AS jsonb),:derived)"
                    ),
                    params,
                )
                conn.execute(
                    text(
                        "INSERT INTO app.evidence_anchors(workspace_id,source_id,id,revision_id,original_object_id,locator_kind,page,text_artifact_id,start_char,end_char,transform) VALUES (:w,:s,:anchor,:r,:original,:kind,:page,:text_obj,:start,:end,CAST(:transform AS jsonb))"
                    ),
                    params,
                )
                conn.execute(
                    text(
                        "INSERT INTO app.segment_evidence(workspace_id,source_id,segment_id,anchor_id,revision_id,relation,producer) VALUES (:w,:s,:seg,:anchor,:r,:relation,'documents-v1')"
                    ),
                    params,
                )
                conn.execute(
                    text(
                        "INSERT INTO app.citation_records(workspace_id,source_id,id,segment_id,anchor_id) VALUES (:w,:s,:citation,:seg,:anchor)"
                    ),
                    params,
                )
                if entry.get("text"):
                    conn.execute(
                        text(
                            "INSERT INTO app.searchable_text(workspace_id,source_id,segment_id,text_content,lexemes) VALUES (:w,:s,:seg,:content,to_tsvector('simple',:content))"
                        ),
                        params,
                    )
                ordinal += 1
        summary["segments"] = ordinal
        conn.execute(
            text(
                "UPDATE app.segment_sets SET status='ready',manifest=CAST(:manifest AS jsonb) WHERE workspace_id=:w AND source_id=:s AND id=:set"
            ),
            dict(v, manifest=json.dumps(summary)),
        )
        # Evidence and successful job status become visible in one commit.
        updated = conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status='stored',error_code=NULL,manifest=CAST(:manifest AS jsonb),lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() RETURNING id"
            ),
            dict(v, manifest=json.dumps(summary)),
        ).first()
        if not updated:
            raise InvalidFile("LEASE_EXPIRED")
    return summary


def process(engine, objects, settings, job):
    actor = UUID(str(job["requested_by"]))
    v = scope(job)
    with transaction(engine, actor) as conn:
        source_scope(conn, v["w"], v["s"], write=True)
        fence(conn, v)
        original = (
            conn.execute(
                text(
                    "SELECT r.asset_id,r.original_object_id,r.sha256,o.object_key,o.mime_type,o.size_bytes,p.profile_hash FROM app.asset_revisions r JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id) JOIN app.processing_runs p ON (p.workspace_id,p.source_id,p.revision_id)=(r.workspace_id,r.source_id,r.id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r AND p.id=:run"
                ),
                v,
            )
            .mappings()
            .first()
        )
        if not original:
            raise InvalidFile("SOURCE_UNAVAILABLE")
        if original["profile_hash"] != PROFILE:
            raise InvalidFile("DOCUMENT_PROFILE_MISMATCH")
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        path = directory / (
            "original.docx"
            if "wordprocessingml" in original["mime_type"]
            else "original"
        )
        response = objects.get_object(settings.minio_bucket, original["object_key"])
        try:
            size = 0
            with path.open("wb") as output:
                for block in response.stream(1024 * 1024):
                    size += len(block)
                    if size > settings.max_upload_bytes:
                        raise InvalidFile("FILE_TOO_LARGE")
                    output.write(block)
        finally:
            response.close()
            response.release_conn()
        if size != original["size_bytes"] or digest(path) != original["sha256"]:
            raise InvalidFile("ORIGINAL_HASH_MISMATCH")

        def progress(data):
            with transaction(engine, actor) as conn:
                source_scope(conn, v["w"], v["s"], write=True)
                fence(conn, v)
                conn.execute(
                    text(
                        "UPDATE app.ingestion_jobs SET manifest=CAST(:manifest AS jsonb),updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token"
                    ),
                    dict(v, manifest=json.dumps(data)),
                )

        manifest = run_extractor(directory, original["mime_type"], progress)
        if digest(path) != original["sha256"]:
            raise InvalidFile("ORIGINAL_HASH_MISMATCH")
        try:
            return publish(
                engine, objects, settings, job, original, directory, manifest
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                raise InvalidFile("DOCUMENT_STORAGE_LIMIT") from None
            raise
