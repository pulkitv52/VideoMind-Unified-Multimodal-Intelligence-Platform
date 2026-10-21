"""Download manifest-pinned checkpoints into the project cache."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))


def main():
    from huggingface_hub import snapshot_download

    manifest = json.loads(
        (ROOT / "evaluation/manifests/model-revisions.json").read_text()
    )
    for repo, entry in manifest.items():
        snapshot_download(repo, revision=entry["revision"])


if __name__ == "__main__":
    main()
