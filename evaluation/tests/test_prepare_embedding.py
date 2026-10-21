"""Checkpoint preparation checks hash integrity without downloading model weights."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import pytest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/prepare_embedding.py"
    spec = importlib.util.spec_from_file_location("prepare_embedding_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    manifest = tmp_path / "evaluation/manifests"
    manifest.mkdir(parents=True)
    payload = b"pinned fixture checkpoint"
    (manifest / "embedding-files.json").write_text(
        json.dumps({"config.json": hashlib.sha256(payload).hexdigest()})
    )
    return module, tmp_path, payload


def test_download_validates_before_publish_and_reuses_target(setup, monkeypatch):
    module, root, payload = setup
    urls = []

    def fetch(url, timeout):
        urls.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(module, "urlopen", fetch)
    module.prepare()
    module.prepare()
    assert len(urls) == 1 and module.REVISION in urls[0]
    assert (root / ".local/models/embedding/config.json").read_bytes() == payload


def test_corrupt_download_is_not_published(setup, monkeypatch):
    module, root, _ = setup
    monkeypatch.setattr(
        module, "urlopen", lambda *args, **kw: io.BytesIO(b"corrupt checkpoint")
    )
    with pytest.raises(RuntimeError):
        module.prepare()
    assert not (root / ".local/models/embedding/config.json").exists()
    assert not list((root / ".local/models/embedding").glob(".checkpoint-*"))
