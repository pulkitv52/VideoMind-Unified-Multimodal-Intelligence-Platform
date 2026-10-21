"""Import the prepared 30-video sample pack through authenticated intake APIs."""

import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.datasets.video_pack import MANIFEST, sha
from scripts.demo_intake import call, ensure_source, wait

COLLECTIONS = {
    "CAVIAR": "CAVIAR - Stores and lobby",
    "UR Fall": "UR Fall - Falls and daily activities",
    "Roadscapes": "Roadscapes - Day and night driving",
}
EXPECTED = {"CAVIAR": 15, "UR Fall": 10, "Roadscapes": 5}


def attribution(dataset, items):
    lines = [
        f"# {dataset}: VideoMind local sample pack",
        "",
        "For noncommercial local development. These clips are not a clinical or retrieval benchmark.",
        "",
        "Uploaded MP4s are video-only resized derivatives, not upstream originals. "
        "Upstream files, annotations and per-frame source/time mappings are retained under "
        "`.local/datasets/video30/` on the host. The reproducibility manifest is "
        "`evaluation/manifests/video30.json`.",
        "",
        "Conversion: PyAV/libx264, maximum width 640, CRF 23, source timing retained except explicit duplicate-PTS repairs. "
        "Original audio, if present, is retained only in the upstream file. "
        "No videos have been embedded or made searchable.",
        "",
    ]
    if dataset == "UR Fall":
        lines += [
            "The falls are staged research recordings, not hospital CCTV. "
            "Camera0 RGB frames use the publisher synchronization CSV. "
            "Cite Kwolek and Kepski (2014), Human fall detection on embedded platform using depth maps and wireless accelerometer.",
            "",
        ]
    if dataset == "CAVIAR":
        lines += [
            "Includes shopping-centre and staged lobby scenes. Sequence names are selection hints; "
            "events have not been independently relabeled. Publisher XML is retained locally.",
            "",
        ]
    if dataset == "Roadscapes":
        lines += [
            "Three daytime and two nighttime sequences. Publisher descriptions were generated "
            "with Gemini 1.5 Pro and were not manually verified; they are not ground truth.",
            "",
        ]
    for item in items:
        derived = item["derivative"]
        lines += [
            f"## {item['id']}",
            "",
            f"- File: {Path(derived['path']).name}",
            f"- Publisher: {item['homepage']}",
            f"- Credit: {item['credit']}",
            f"- License: {item['license']}",
            f"- Upstream: {item['original']['url']}",
            f"- Original SHA-256: {item['original']['sha256']}",
            f"- Derivative SHA-256: {derived['sha256']}",
            f"- Duplicate-PTS frames adjusted by playback ticks: {derived.get('adjusted_frames', 0)}",
            f"- Frame mapping: {derived['mapping_path']}",
            f"- Mapping SHA-256: {derived['mapping_sha256']}",
            "",
        ]
        if item.get("license_url"):
            lines += [f"License terms: {item['license_url']}", ""]
    target = (
        ROOT
        / f"evaluation/manifests/video30-{dataset.lower().replace(' ', '-')}-ATTRIBUTION.md"
    )
    target.write_text("\n".join(lines))
    return target


def main():
    items = json.loads(MANIFEST.read_text())["items"]
    assert len(items) == 30 and len({i["id"] for i in items}) == 30
    for item in items:
        assert sha(ROOT / item["original"]["path"]) == item["original"]["sha256"]
        assert sha(ROOT / item["derivative"]["path"]) == item["derivative"]["sha256"]
        assert (
            sha(ROOT / item["derivative"]["mapping_path"])
            == item["derivative"]["mapping_sha256"]
        )
    call("/api/auth/login", json.loads((ROOT / ".local/owner.json").read_text()))
    workspace = call("/api/workspaces")[0]["id"]
    started = time.perf_counter()
    reports = []
    for dataset, name in COLLECTIONS.items():
        selected = [item for item in items if item["dataset"] == dataset]
        assert len(selected) == EXPECTED[dataset]
        paths = [ROOT / item["derivative"]["path"] for item in selected]
        paths.append(attribution(dataset, selected))
        source = ensure_source(workspace, name, "upload")
        base = f"/api/workspaces/{workspace}/sources/{source['id']}"
        new_uploads = unchanged_uploads = 0
        for path in paths:
            response = call(
                base + "/files?filename_value=" + urllib.parse.quote(path.name),
                path.read_bytes(),
                raw=True,
            )
            unchanged_uploads += int(response["unchanged"])
            new_uploads += int(not response["unchanged"])
            print(
                "Received",
                path.name,
                "unchanged" if response["unchanged"] else "new",
                flush=True,
            )
        jobs = wait(base)
        assert all(job["status"] == "stored" for job in jobs), [
            (j["status"], j["error_code"]) for j in jobs
        ]
        assets = call(base + "/assets")
        for path in paths:
            asset = next(a for a in assets if a["title"] == path.name)
            content = call(base + f"/assets/{asset['id']}/original", raw=True)
            assert hashlib.sha256(content).hexdigest() == sha(path)
        # Repeat one clip to check that intake remains idempotent.
        repeated = call(
            base + "/files?filename_value=" + urllib.parse.quote(paths[0].name),
            paths[0].read_bytes(),
            raw=True,
        )
        assert repeated["unchanged"]
        reports.append(
            {
                "dataset": dataset,
                "collection": name,
                "videos": len(selected),
                "attribution_files": 1,
                "assets": len(assets),
                "new_uploads_in_this_run": new_uploads,
                "unchanged_uploads_in_this_run": unchanged_uploads,
                "all_jobs_stored": True,
                "all_download_checksums_match": True,
                "duplicate_upload_noop": True,
            }
        )
        print("Verified collection:", name, flush=True)
    result = {
        "scope": "Dataset preparation, authenticated intake and original-download verification only; no search evaluation",
        "collections": reports,
        "videos": 30,
        "upstream_bytes": sum(i["original"]["bytes"] for i in items),
        "derived_video_bytes": sum(i["derivative"]["bytes"] for i in items),
        "frames": sum(i["derivative"]["frames"] for i in items),
        "elapsed_import_seconds": round(time.perf_counter() - started, 2),
        "gpu_used": False,
        "timing_scope": "This run only; may reuse already imported assets; excludes download and conversion",
    }
    target = ROOT / "evaluation/reports/video30-intake.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print("Verified 30 videos. Report:", target, flush=True)


if __name__ == "__main__":
    main()
