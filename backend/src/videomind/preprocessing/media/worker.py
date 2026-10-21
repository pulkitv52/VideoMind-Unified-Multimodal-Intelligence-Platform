"""Durable media processing with atomic evidence and mapped playback publication."""

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
from videomind.ingestion.service import source_scope, digest
from videomind.ingestion.jobs import scope, fence
from .contracts import validate_manifest
from .profile import CONFIG, PROFILE


def run_extractor(directory, progress=None):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "LANG": "C.UTF-8",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    child = subprocess.Popen(
        [sys.executable, "-m", "videomind.preprocessing.media.extract", str(directory)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + CONFIG["wall_seconds"]
    last = {"stage": "decode"}
    checked = 0
    try:
        while child.poll() is None:
            if time.monotonic() > deadline:
                raise InvalidFile("MEDIA_TIMEOUT")
            if progress and time.monotonic() - checked > 2:
                path = directory / "progress.json"
                try:
                    if path.exists() and path.stat().st_size < 8192:
                        last = json.loads(path.read_text())
                except (ValueError, OSError):
                    pass
                progress(last)
                checked = time.monotonic()
            time.sleep(0.2)
        path = directory / "result.json"
        if not path.exists() or path.stat().st_size > 32 * 1024**2:
            raise InvalidFile("MEDIA_RESOURCE_LIMIT")
        result = json.loads(path.read_text())
        if not result["ok"]:
            raise InvalidFile(result["error_code"])
        return validate_manifest(result["manifest"], directory)
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def publish(engine, objects, settings, job, original, directory, manifest):
    actor = UUID(str(job["requested_by"]))
    v = scope(job)
    names = {manifest["playback_file"]}
    names.update(f["file"] for f in manifest["frames"])
    names.update(
        t["canonical_file"] for t in manifest["tracks"] if t["kind"] == "audio"
    )
    names.update(s["file"] for s in manifest["segments"])
    (directory / "mapping.json").write_text(json.dumps(manifest))
    names.add("mapping.json")
    artifacts = {}
    for name in sorted(names):
        path = directory / name
        oid = uuid4()
        sha = digest(path)
        artifacts[name] = {
            "id": oid,
            "sha": sha,
            "size": path.stat().st_size,
            "key": f"{v['w']}/{v['s']}/media/{oid}/{sha}",
            "path": path,
            "mime": {
                ".mp4": "video/mp4",
                ".wav": "audio/wav",
                ".jpg": "image/jpeg",
                ".json": "application/json",
            }[path.suffix],
        }
    if sum(a["size"] for a in artifacts.values()) > CONFIG["max_output_bytes"]:
        raise InvalidFile("MEDIA_OUTPUT_LIMIT")
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
                raise InvalidFile("MEDIA_RESERVATION_EXPIRED")
            with a["path"].open("rb") as stream:
                objects.put_object(
                    settings.minio_bucket,
                    a["key"],
                    stream,
                    a["size"],
                    content_type=a["mime"],
                    part_size=max(128 * 1024**2, 5 * 1024**2),
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
        summary = {
            "kind": "media",
            "profile": PROFILE,
            "configuration": CONFIG,
            "origin_ms": manifest["origin_ms"],
            "end_ms": manifest["end_ms"],
            "playback_kind": manifest["playback_kind"],
            "asr_status": manifest["asr_status"],
            "partial": bool(manifest["warnings"]),
            "warnings": manifest["warnings"],
            "segments": len(manifest["segments"]),
            "searchable": False,
            "search_inputs_ready": True,
            "producer": "media-v1",
        }
        conn.execute(
            text(
                "INSERT INTO app.segment_sets(workspace_id,source_id,id,revision_id,processing_run_id,segmenter_profile,status,manifest) VALUES (:w,:s,:set,:r,:run,:profile,'building',CAST(:manifest AS jsonb))"
            ),
            dict(v, profile=PROFILE, manifest=json.dumps(summary)),
        )
        payload = dict(
            summary,
            tracks=[
                {k: value for k, value in t.items() if k != "timing"}
                for t in manifest["tracks"]
            ],
            frames=[
                dict(f, object_id=str(artifacts[f["file"]]["id"]))
                for f in manifest["frames"]
            ],
            playback_object_id=str(artifacts[manifest["playback_file"]]["id"]),
            mapping_object_id=str(artifacts["mapping.json"]["id"]),
        )
        conn.execute(
            text(
                "INSERT INTO app.media_presentations(workspace_id,source_id,segment_set_id,revision_id,playback_object_id,mapping_object_id,manifest) VALUES (:w,:s,:set,:r,:play,:mapping,CAST(:manifest AS jsonb))"
            ),
            dict(
                v,
                play=artifacts[manifest["playback_file"]]["id"],
                mapping=artifacts["mapping.json"]["id"],
                manifest=json.dumps(payload),
            ),
        )
        for a in artifacts.values():
            conn.execute(
                text(
                    "INSERT INTO app.media_artifacts(workspace_id,source_id,segment_set_id,object_id) VALUES (:w,:s,:set,:i)"
                ),
                dict(v, i=a["id"]),
            )
        for ordinal, segment in enumerate(manifest["segments"]):
            seg, anchor, cite = uuid4(), uuid4(), uuid4()
            idx = int(segment["track"].split(":")[1])
            track = next(t for t in manifest["tracks"] if t["index"] == idx)
            playback = (
                artifacts[manifest["playback_file"]]["id"]
                if segment["track"].startswith("video")
                or manifest["playback_kind"] == "video"
                and idx
                == next(
                    (t["index"] for t in manifest["tracks"] if t["kind"] == "audio"),
                    None,
                )
                else artifacts[track["canonical_file"]]["id"]
            )
            transform = {
                "profile": PROFILE,
                "playback_object_id": str(playback),
                "playback_origin_ms": manifest["origin_ms"],
                "playback_kind": (
                    "video"
                    if playback == artifacts[manifest["playback_file"]]["id"]
                    and manifest["playback_kind"] == "video"
                    else "audio"
                ),
                "mapping_object_id": str(artifacts["mapping.json"]["id"]),
                "words": segment["words"],
                "frames": [
                    dict(f, object_id=str(artifacts[f["file"]]["id"]))
                    for f in segment["frames"]
                ],
            }
            params = dict(
                v,
                seg=seg,
                anchor=anchor,
                cite=cite,
                rep=segment["representation"],
                ordinal=ordinal,
                content=segment["text"],
                derived=artifacts[segment["file"]]["id"],
                original=original["original_object_id"],
                track=segment["track"],
                start=segment["start_ms"],
                end=segment["end_ms"],
                transform=json.dumps(transform),
                quality=json.dumps({"confidence_calibrated": False}),
                relation=(
                    "transcribed_from"
                    if segment["representation"] == "transcript"
                    else "depicts"
                ),
                language="en" if segment["representation"] == "transcript" else None,
            )
            conn.execute(
                text(
                    "INSERT INTO app.segments(workspace_id,source_id,id,segment_set_id,revision_id,representation,ordinal,text_content,language,producer,quality,derived_object_id) VALUES (:w,:s,:seg,:set,:r,:rep,:ordinal,:content,:language,'media-v1',CAST(:quality AS jsonb),:derived)"
                ),
                params,
            )
            conn.execute(
                text(
                    "INSERT INTO app.evidence_anchors(workspace_id,source_id,id,revision_id,original_object_id,locator_kind,start_ms,end_ms,track,transform) VALUES (:w,:s,:anchor,:r,:original,'temporal',:start,:end,:track,CAST(:transform AS jsonb))"
                ),
                params,
            )
            conn.execute(
                text(
                    "INSERT INTO app.segment_evidence(workspace_id,source_id,segment_id,anchor_id,revision_id,relation,producer) VALUES (:w,:s,:seg,:anchor,:r,:relation,'media-v1')"
                ),
                params,
            )
            conn.execute(
                text(
                    "INSERT INTO app.citation_records(workspace_id,source_id,id,segment_id,anchor_id) VALUES (:w,:s,:cite,:seg,:anchor)"
                ),
                params,
            )
            if segment["text"]:
                conn.execute(
                    text(
                        "INSERT INTO app.searchable_text(workspace_id,source_id,segment_id,text_content,lexemes) VALUES (:w,:s,:seg,:content,to_tsvector('simple',:content))"
                    ),
                    params,
                )
        conn.execute(
            text(
                "UPDATE app.segment_sets SET status='ready' WHERE workspace_id=:w AND source_id=:s AND id=:set"
            ),
            v,
        )
        done = conn.execute(
            text(
                "UPDATE app.ingestion_jobs SET status='stored',manifest=CAST(:manifest AS jsonb),error_code=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j AND status='running' AND lease_token=:token AND lease_expires_at>now() RETURNING id"
            ),
            dict(v, manifest=json.dumps(summary)),
        ).first()
        if not done:
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
                    "SELECT r.asset_id,r.original_object_id,r.sha256,o.object_key,o.size_bytes FROM app.asset_revisions r JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id) WHERE r.workspace_id=:w AND r.source_id=:s AND r.id=:r"
                ),
                v,
            )
            .mappings()
            .one()
        )
        profile = conn.execute(
            text(
                "SELECT profile_hash FROM app.processing_runs WHERE workspace_id=:w AND source_id=:s AND id=:run"
            ),
            v,
        ).scalar_one()
        if profile != PROFILE:
            raise InvalidFile("MEDIA_PROFILE_MISMATCH")
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        path = directory / "original"
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
                        "UPDATE app.ingestion_jobs SET manifest=CAST(:manifest AS jsonb),updated_at=now(),lease_expires_at=now()+interval '5 minutes' WHERE workspace_id=:w AND source_id=:s AND id=:j AND lease_token=:token AND lease_expires_at>now()"
                    ),
                    dict(v, manifest=json.dumps(data)),
                )

        manifest = run_extractor(directory, progress)
        if digest(path) != original["sha256"]:
            raise InvalidFile("ORIGINAL_HASH_MISMATCH")
        try:
            return publish(
                engine, objects, settings, job, original, directory, manifest
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                raise InvalidFile("MEDIA_STORAGE_LIMIT") from None
            raise
