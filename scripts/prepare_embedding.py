"""Prepare hash-pinned model files from local caches or the exact public revision."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def prepare():
    cache = (
        ROOT
        / ".cache/huggingface/hub/models--google--embeddinggemma-2/snapshots"
        / REVISION
    )
    target = ROOT / ".local/models/embedding"
    target.mkdir(parents=True, exist_ok=True)
    expected = json.loads(
        (ROOT / "evaluation/manifests/embedding-files.json").read_text()
    )
    for name, sha in sorted(expected.items()):
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and digest(dst) == sha:
            continue
        source = cache / name
        fd, temp = tempfile.mkstemp(prefix=".checkpoint-", dir=dst.parent)
        path = Path(temp)
        try:
            with os.fdopen(fd, "wb") as out:
                if source.is_file() and digest(source) == sha:
                    with source.open("rb") as inp:
                        shutil.copyfileobj(inp, out, 1024 * 1024)
                else:
                    url = f'https://huggingface.co/google/embeddinggemma-2/resolve/{REVISION}/{quote(name,safe="/")}'
                    with urlopen(url, timeout=60) as inp:
                        shutil.copyfileobj(inp, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            if digest(path) != sha:
                raise RuntimeError("Pinned checkpoint/processor identity mismatch")
            path.chmod(0o644)
            path.replace(dst)
        finally:
            path.unlink(missing_ok=True)
    manifest = target / "manifest.json"
    manifest.write_text(json.dumps(expected, indent=2) + "\n")
    print("Pinned embedding checkpoint prepared")


if __name__ == "__main__":
    prepare()
