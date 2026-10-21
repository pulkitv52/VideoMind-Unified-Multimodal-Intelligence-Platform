import base64
import io
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from videomind.retrieval.image_query import normalize, MAX_BYTES
from videomind.retrieval.contracts import ImageSearchRequest
from videomind.retrieval.config import configuration


def test_image_request_is_dense_only_and_keeps_query_payload_out_of_policy():
    body = ImageSearchRequest(
        workspace_id="00000000-0000-0000-0000-000000000001", image_base64="private"
    )
    policy, _ = configuration(body)
    assert policy["mode"] == "dense" and policy["query_kind"] == "image"
    assert "private" not in str(policy)
    with pytest.raises(ValidationError):
        ImageSearchRequest(**(body.model_dump() | {"mode": "hybrid"}))


def test_invalid_and_oversized_images_never_reach_decoder(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: pytest.fail("Decoder must not run")
    )
    for encoded, status in (
        ("invalid!", 422),
        (base64.b64encode(b"x" * (MAX_BYTES + 1)).decode(), 413),
    ):
        with pytest.raises(HTTPException) as exc:
            normalize(encoded)
        assert exc.value.status_code == status


def test_decoder_is_bounded_and_does_not_receive_service_credentials(monkeypatch):
    def decode(args, **kwargs):
        assert kwargs["timeout"] == 10
        assert not any("DATABASE" in key or "SECRET" in key for key in kwargs["env"])
        return SimpleNamespace(returncode=0, stdout=b"normalized")

    monkeypatch.setattr("subprocess.run", decode)
    assert (
        normalize(base64.b64encode(b"input").decode())
        == base64.b64encode(b"normalized").decode()
    )
