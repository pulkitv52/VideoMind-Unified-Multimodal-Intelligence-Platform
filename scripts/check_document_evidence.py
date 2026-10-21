"""Read-only checks of retained demo originals and Phase 3 document evidence.

Uses the generated local owner credentials without printing them. Run with the
backend development environment after scripts/dev.py up and verify.
"""

import hashlib
import json
from pathlib import Path
import subprocess

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    pack = json.loads((ROOT / "evaluation/manifests/video30.json").read_text())
    expected = {
        Path(i["derivative"]["path"]).name: i["derivative"]["sha256"]
        for i in pack["items"]
    }
    result = {
        "scope": "Authenticated original preservation and document evidence, CPU only",
        "collections": [],
        "files_verified": 0,
        "video_pack_verified": 0,
        "documents_ready": 0,
        "citations_verified": 0,
        "images_verified": 0,
    }
    with httpx.Client(base_url="http://localhost:8080", timeout=30) as client:
        client.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        w = client.get("/api/workspaces").json()[0]["id"]
        for source in client.get(f"/api/workspaces/{w}/sources").json():
            base = f'/api/workspaces/{w}/sources/{source["id"]}'
            assets = []
            cursor = ""
            while True:
                response = client.get(
                    base + "/assets",
                    params={"limit": 200, **({"after": cursor} if cursor else {})},
                )
                response.raise_for_status()
                assets.extend(response.json())
                cursor = response.headers.get("x-next-cursor", "")
                if not cursor:
                    break
            ready = 0
            for asset in assets:
                response = client.get(
                    f'{base}/revisions/{asset["revision_id"]}/original'
                )
                response.raise_for_status()
                sha = hashlib.sha256(response.content).hexdigest()
                assert sha == asset["sha256"]
                result["files_verified"] += 1
                if asset["title"] in expected:
                    assert sha == expected[asset["title"]]
                    result["video_pack_verified"] += 1
                if not asset.get("document"):
                    continue
                assert asset["document"]["status"] == "stored", (
                    asset["title"],
                    asset["document"]["error_code"],
                )
                descriptor = client.get(
                    f'{base}/revisions/{asset["revision_id"]}/document'
                )
                descriptor.raise_for_status()
                data = descriptor.json()
                assert (
                    data["manifest"]["search_inputs_ready"]
                    and not data["manifest"]["searchable"]
                )
                ready += 1
                result["documents_ready"] += 1
                for page in data["pages"]:
                    detail = client.get(
                        f'{base}/revisions/{asset["revision_id"]}/document/pages/{page["page"]}'
                    )
                    detail.raise_for_status()
                    for segment in detail.json()["segments"]:
                        citation = client.get(
                            f'{base}/citations/{segment["citation_id"]}'
                        )
                        citation.raise_for_status()
                        assert (
                            citation.json()["revision_id"] == asset["revision_id"]
                            and citation.json()["segment_set_id"]
                            == data["segment_set_id"]
                        )
                        result["citations_verified"] += 1
                    if page["image_object_id"]:
                        image = client.get(
                            f'{base}/revisions/{asset["revision_id"]}/document/objects/{page["image_object_id"]}'
                        )
                        image.raise_for_status()
                        assert image.content.startswith(b"\x89PNG")
                        result["images_verified"] += 1
            result["collections"].append(
                {"name": source["name"], "files": len(assets), "documents_ready": ready}
            )
        health = client.get("/health/ready")
        health.raise_for_status()
        result["readiness"] = health.json()
        assert result["video_pack_verified"] == 30
        result["storage"] = client.get(f"/api/workspaces/{w}/storage").json()
    code = """
import hashlib,json
from pathlib import Path
packages=Path('/usr/share/videomind-packages.txt').read_text()
wanted=('libreoffice-core','libreoffice-writer','poppler-utils','tesseract-ocr','tesseract-ocr-eng','fonts-dejavu-core','libseccomp2')
versions={line.split()[0]:line.split()[1] for line in packages.splitlines() if line.split()[0].split(':')[0] in wanted}
files={'tesseract_english':'/usr/share/tesseract-ocr/5/tessdata/eng.traineddata','dejavu_sans':'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','packages':'/usr/share/videomind-packages.txt'}
print(json.dumps({'packages':versions,'sha256':{k:hashlib.sha256(Path(p).read_bytes()).hexdigest() for k,p in files.items()}}))
"""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "infra/compose/compose.yaml"),
            "exec",
            "-T",
            "worker",
            "python",
            "-",
        ],
        input=code,
        text=True,
        capture_output=True,
        check=True,
    )
    result["producer_runtime"] = json.loads(completed.stdout)
    (ROOT / "evaluation/reports/phase3-preservation.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "files_verified",
                    "video_pack_verified",
                    "documents_ready",
                    "citations_verified",
                    "images_verified",
                    "readiness",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
