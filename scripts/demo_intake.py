"""Import the licensed starter samples and generated fixtures through the real API."""

import hashlib
import http.cookiejar
import json
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
client = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def call(path, body=None, raw=False):
    data = body if raw else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=data,
        headers={
            "Content-Type": "application/octet-stream" if raw else "application/json"
        },
    )
    try:
        with client.open(req, timeout=140) as response:
            result = response.read()
            return (
                result
                if raw and path.endswith("/original")
                else json.loads(result) if result else None
            )
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read()).get("detail", "Request failed")
        raise RuntimeError(f"API returned {exc.code}: {detail}") from None


def ensure_source(w, name, kind, folder=""):
    sources = call(f"/api/workspaces/{w}/sources")
    existing = next(
        (s for s in sources if s["name"] == name and s["connector_kind"] == kind), None
    )
    return existing or call(
        f"/api/workspaces/{w}/sources",
        {"name": name, "connector_kind": kind, "folder": folder},
    )


def wait(base):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        jobs = call(base + "/jobs")
        if jobs and all(j["status"] in {"stored", "failed", "cancelled"} for j in jobs):
            return jobs
        time.sleep(1)
    raise RuntimeError("Demo intake did not complete within two minutes")


def main():
    public = ROOT / ".local/datasets/public-starter"
    manifest = json.loads(
        (ROOT / "evaluation/manifests/public-starter.json").read_text()
    )
    for item in manifest["assets"]:
        assert (
            hashlib.sha256((public / item["filename"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    fixture = ROOT / "evaluation/fixtures/generated"
    paths = [
        public / "chelsea.png",
        public / "dog.wav",
        ROOT / "evaluation/manifests/public-starter-ATTRIBUTION.md",
        fixture / "procedure.txt",
        fixture / "scanned-page.pdf",
        fixture / "renderer/renderer-smoke.docx",
        fixture / "speech.wav",
        fixture / "beeps.wav",
        fixture / "silent.mp4",
        fixture / "spoken.mp4",
    ]
    assert all(
        p.is_file() for p in paths
    ), "Generate Phase 0 fixtures and fetch the two licensed samples first"
    call("/api/auth/login", json.loads((ROOT / ".local/owner.json").read_text()))
    w = call("/api/workspaces")[0]["id"]
    source = ensure_source(w, "Starter dataset", "upload")
    base = f"/api/workspaces/{w}/sources/{source['id']}"
    started = time.perf_counter()
    uploads = []
    for path in paths:
        response = call(
            base + "/files?filename_value=" + urllib.parse.quote(path.name),
            path.read_bytes(),
            raw=True,
        )
        uploads.append(
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "unchanged": response["unchanged"],
            }
        )
        print("Received", path.name, flush=True)
    jobs = wait(base)
    assert all(j["status"] == "stored" for j in jobs), [
        (j["status"], j["error_code"]) for j in jobs
    ]
    assets = call(base + "/assets")
    for path in paths:
        asset = next(a for a in assets if a["title"] == path.name)
        original = call(base + f"/assets/{asset['id']}/original", raw=True)
        assert (
            hashlib.sha256(original).hexdigest()
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
    repeated = call(
        base + "/files?filename_value=dog.wav",
        (public / "dog.wav").read_bytes(),
        raw=True,
    )
    assert repeated["unchanged"]
    folder = ROOT / ".local/imports/starter"
    folder.mkdir(parents=True, exist_ok=True, mode=0o755)
    for path in (
        public / "chelsea.png",
        public / "dog.wav",
        ROOT / "evaluation/manifests/public-starter-ATTRIBUTION.md",
    ):
        target = folder / path.name
        shutil.copyfile(path, target)
        target.chmod(0o644)
    connected = ensure_source(w, "Local starter folder", "local_folder", "starter")
    folder_base = f"/api/workspaces/{w}/sources/{connected['id']}"
    call(folder_base + "/sync", {})
    folder_jobs = wait(folder_base)
    assert all(j["status"] == "stored" for j in folder_jobs), [
        (j["status"], j["error_code"]) for j in folder_jobs
    ]
    # A second complete scan must preserve existing revision/job identities.
    before = call(folder_base + "/assets")
    call(folder_base + "/sync", {})
    rescanned = wait(folder_base)
    after = call(folder_base + "/assets")
    assert {a["revision_id"] for a in before} == {a["revision_id"] for a in after}
    report = {
        "scope": "Original intake and format checks only; no OCR/ASR/embedding/search benchmark",
        "uploads": uploads,
        "upload_assets": len(assets),
        "all_original_checksums_match": True,
        "duplicate_upload_noop": True,
        "folder_assets": len(after),
        "folder_rescan_same_revisions": True,
        "folder_latest_sync": rescanned[0]["manifest"],
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    target = ROOT / "evaluation/reports/phase2-starter-intake.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print("Starter dataset and local folder validated. Report:", target, flush=True)


if __name__ == "__main__":
    main()
