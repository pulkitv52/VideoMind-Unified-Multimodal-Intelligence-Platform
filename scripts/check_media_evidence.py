"""Read-only verification of local demo media, mappings, ranges and citations."""

import hashlib
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = {
        "scope": "Existing demo corpus, CPU processing and evidence; not retrieval evaluation",
        "files_verified": 0,
        "media_ready": 0,
        "citations_verified": 0,
        "native_video_windows": 0,
        "native_audio_windows": 0,
        "transcript_segments": 0,
        "decoded_video_frames": 0,
        "max_frame_mapping_error_ms": 0,
        "collections": [],
        "warnings": [],
    }
    with httpx.Client(base_url="http://localhost:8080", timeout=60) as client:
        client.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        w = client.get("/api/workspaces").json()[0]["id"]
        deadline = time.monotonic() + 900
        while True:
            sources = client.get(f"/api/workspaces/{w}/sources").json()
            pending = []
            failed = []
            for s in sources:
                base = f'/api/workspaces/{w}/sources/{s["id"]}'
                rows = client.get(base + "/assets").json()
                for row in rows:
                    m = row.get("media")
                    if not m:
                        continue
                    if m["status"] in ("queued", "running"):
                        pending.append(row["title"])
                    elif m["status"] != "stored":
                        failed.append((row["title"], m["error_code"]))
            if failed:
                raise RuntimeError(f"Media failures: {failed}")
            if not pending:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Media still processing")
            time.sleep(3)
        for s in sources:
            base = f'/api/workspaces/{w}/sources/{s["id"]}'
            assets = client.get(base + "/assets").json()
            ready = 0
            for asset in assets:
                original = client.get(
                    f'{base}/revisions/{asset["revision_id"]}/original'
                )
                original.raise_for_status()
                assert hashlib.sha256(original.content).hexdigest() == asset["sha256"]
                report["files_verified"] += 1
                if not asset.get("media"):
                    continue
                r = asset["revision_id"]
                d = client.get(f"{base}/revisions/{r}/media")
                d.raise_for_status()
                d = d.json()
                ss = d["segment_set_id"]
                m = d["manifest"]
                ready += 1
                report["media_ready"] += 1
                report["warnings"].extend(m["warnings"])
                url = f'{base}/revisions/{r}/media/objects/{d["playback_object_id"]}?segment_set_id={ss}'
                head = client.head(url)
                head.raise_for_status()
                size = int(head.headers["content-length"])
                part = client.get(url, headers={"Range": "bytes=0-31"})
                assert (
                    part.status_code == 206
                    and len(part.content) == 32
                    and part.headers["content-range"] == f"bytes 0-31/{size}"
                )
                suffix = client.get(url, headers={"Range": "bytes=-16"})
                assert suffix.status_code == 206 and len(suffix.content) == 16
                mapping = client.get(
                    f'{base}/revisions/{r}/media/objects/{d["mapping_object_id"]}?segment_set_id={ss}'
                )
                mapping.raise_for_status()
                mapping = mapping.json()
                video = next(
                    (t for t in mapping["tracks"] if t["kind"] == "video"), None
                )
                if video:
                    report["decoded_video_frames"] += len(video["timing"])
                    errors = [
                        abs(p - (o["original_ms"] - m["origin_ms"]))
                        for o, p in zip(video["timing"], mapping["playback_frame_ms"])
                    ]
                    assert (
                        len(video["timing"]) == len(mapping["playback_frame_ms"])
                        and max(errors) <= 50
                    )
                    report["max_frame_mapping_error_ms"] = max(
                        report["max_frame_mapping_error_ms"], max(errors)
                    )
                segments = []
                after = -1
                while True:
                    rows = client.get(
                        f"{base}/revisions/{r}/media/segments",
                        params={"segment_set_id": ss, "after": after, "limit": 500},
                    )
                    rows.raise_for_status()
                    value = rows.json()
                    segments.extend(value["items"])
                    if value["next"] is None:
                        break
                    after = value["next"]
                for segment in segments:
                    c = client.get(f'{base}/citations/{segment["citation_id"]}')
                    c.raise_for_status()
                    c = c.json()
                    assert (
                        c["revision_id"] == r
                        and c["segment_set_id"] == ss
                        and c["start_ms"] == segment["start_ms"]
                        and c["end_ms"] == segment["end_ms"]
                    )
                    report["citations_verified"] += 1
                    key = {
                        "video": "native_video_windows",
                        "audio": "native_audio_windows",
                        "transcript": "transcript_segments",
                    }[segment["representation"]]
                    report[key] += 1
                for track in mapping["tracks"]:
                    if track["kind"] != "audio":
                        continue
                    native = sorted(
                        (
                            x
                            for x in segments
                            if x["representation"] == "audio"
                            and x["track"] == f'audio:{track["index"]}'
                        ),
                        key=lambda x: x["start_ms"],
                    )
                    assert (
                        native and native[0]["start_ms"] == track["canonical_origin_ms"]
                    )
                    cursor = native[0]["start_ms"]
                    for clip in native:
                        assert clip["start_ms"] <= cursor
                        cursor = max(cursor, clip["end_ms"])
                    assert cursor == track["canonical_origin_ms"] + round(
                        track["canonical_samples"] / track["canonical_rate"] * 1000
                    )
            report["collections"].append(
                {"name": s["name"], "originals": len(assets), "media_ready": ready}
            )
        health = client.get("/health/ready")
        health.raise_for_status()
        report["readiness"] = health.json()
        report["storage"] = client.get(f"/api/workspaces/{w}/storage").json()
    (ROOT / "evaluation/reports/phase4-media.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
