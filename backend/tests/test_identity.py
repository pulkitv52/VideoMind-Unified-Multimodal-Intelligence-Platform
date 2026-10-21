from fastapi.testclient import TestClient
from videomind.config import Settings
from videomind.identity.security import password_hash, token_hash, verify_password
from videomind.main import create_app


def test_password_hash_is_salted_and_verifies_only_matching_password():
    value = password_hash("local-test-password")
    assert value != password_hash("local-test-password")
    assert verify_password("local-test-password", value)
    assert not verify_password("wrong-password", value)
    assert not verify_password("anything", "malformed")
    assert token_hash("opaque-token") != "opaque-token"


def test_invalid_credentials_are_not_echoed_and_foreign_origin_is_denied():
    settings = Settings(
        database_url="postgresql+psycopg://unused:password@127.0.0.1/unused",
        redis_url="redis://127.0.0.1:1",
        minio_access_key="unused",
        minio_secret_key="secret",
    )
    assert "password@" not in repr(settings)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/auth/login", json={"username": "bad name", "password": "keep-private"}
        )
        assert response.status_code == 422
        assert "keep-private" not in response.text
        assert response.headers["X-Request-ID"]
        response = client.post(
            "/api/auth/login",
            headers={"Origin": "https://untrusted.example"},
            json={"username": "owner", "password": "keep-private"},
        )
        assert response.status_code == 403


def test_trace_is_propagated_and_reset_without_content_logging():
    from types import SimpleNamespace
    from videomind.infrastructure.telemetry import (
        begin_task,
        end_task,
        publish_trace,
        trace_id,
    )

    value = "4e08c8a3-96d6-4185-959b-ed45314e113e"
    token = trace_id.set(value)
    headers = {}
    publish_trace(headers=headers)
    assert headers["trace_id"] == value
    trace_id.reset(token)
    task = SimpleNamespace(request=SimpleNamespace(headers=headers))
    begin_task(task=task)
    assert trace_id.get() == value
    end_task(task=task, state="SUCCESS")
    assert trace_id.get() is None
