"""Fetch only the two small, licensed, checksummed public starter assets."""

import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads(
        (ROOT / "evaluation/manifests/public-starter.json").read_text()
    )
    target = ROOT / ".local/datasets/public-starter"
    target.mkdir(parents=True, exist_ok=True)
    for item in manifest["assets"]:
        path = target / item["filename"]
        if (
            path.exists()
            and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        ):
            print("Already verified:", item["filename"])
            continue
        with urllib.request.urlopen(item["url"], timeout=30) as response:
            body = response.read(item["bytes"] + 1)
        if (
            len(body) != item["bytes"]
            or hashlib.sha256(body).hexdigest() != item["sha256"]
        ):
            raise RuntimeError("Starter asset integrity check failed")
        path.write_bytes(body)
        print("Verified:", item["filename"])
    shutil.copyfile(
        ROOT / "evaluation/manifests/public-starter-ATTRIBUTION.md",
        target / "ATTRIBUTION.md",
    )
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
