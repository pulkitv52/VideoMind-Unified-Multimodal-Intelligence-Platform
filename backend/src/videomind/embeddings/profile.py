"""Immutable CPU production embedding recipe."""

import hashlib
import json
from pathlib import Path
from videomind.embeddings.contracts import EmbeddingProfile

REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
MODEL = "google/embeddinggemma-2"
ADAPTER = {
    "version": "native-v1",
    "budget": 7500,
    "sampling": "all supplied frames",
    "audio": "mono16000",
    "splitting": "ordered recursive halves without dropping units",
}


def profile(model_manifest: dict, lock_hash: str):
    return EmbeddingProfile(
        model_revision=REVISION,
        processor_revision=REVISION,
        runtime_lock_sha256=lock_hash,
        input_adapter="native-v1",
        preprocessing_hash=hashlib.sha256(
            json.dumps(
                {"adapter": ADAPTER, "files": model_manifest}, sort_keys=True
            ).encode()
        ).hexdigest(),
    )


def installed_profile():
    manifest = json.loads(Path("/models/embedding/manifest.json").read_text())
    expected = json.loads(Path("/usr/share/videomind-embedding-files.json").read_text())
    if manifest != expected:
        raise ValueError("Unpinned checkpoint manifest")
    return profile(
        manifest, hashlib.sha256(Path("/app/backend/uv.lock").read_bytes()).hexdigest()
    )
