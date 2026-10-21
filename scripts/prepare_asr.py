"""Prepare the pinned public CPU ASR checkpoint; reuse the Phase 0 cache."""

import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
EXPECTED = {
    "config.json": "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae",
    "model.bin": "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
    "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
    "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
}
FILES = tuple(EXPECTED)


def prepare():
    target = ROOT / ".local/models/asr"
    target.mkdir(parents=True, exist_ok=True)
    cached = (
        ROOT
        / ".cache/huggingface/hub/models--Systran--faster-whisper-small.en/snapshots"
        / REVISION
    )
    hashes = {}
    for name in FILES:
        path = target / name
        if not path.exists():
            temp = target / (name + ".download")
            if (cached / name).is_file():
                shutil.copyfile(cached / name, temp)
            else:
                with urllib.request.urlopen(
                    f"https://huggingface.co/Systran/faster-whisper-small.en/resolve/{REVISION}/{name}",
                    timeout=180,
                ) as response, temp.open("wb") as output:
                    shutil.copyfileobj(response, output)
            temp.replace(path)
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        hashes[name] = h.hexdigest()
    # model.bin is a content-addressed upstream LFS object validated in Phase 0.
    if hashes != EXPECTED:
        raise RuntimeError("ASR checkpoint hash mismatch")
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "model": "Systran/faster-whisper-small.en",
                "revision": REVISION,
                "files": hashes,
            },
            indent=2,
        )
        + "\n"
    )
    return hashes


if __name__ == "__main__":
    prepare()
    print("Pinned local ASR checkpoint ready")
