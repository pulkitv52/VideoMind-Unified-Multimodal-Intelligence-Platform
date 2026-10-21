"""Private inference boundary and bounded queue priority, without loading a model."""

import threading
from concurrent.futures import ThreadPoolExecutor
import time
from fastapi.testclient import TestClient
from videomind.embeddings import server, runtime
from videomind.embeddings.contracts import EmbeddingProfile


def test_private_auth_profile_validation_and_query_priority(monkeypatch):
    profile = EmbeddingProfile(
        model_revision="a" * 40,
        processor_revision="a" * 40,
        runtime_lock_sha256="b" * 64,
        input_adapter="native-v1",
        preprocessing_hash="c" * 64,
    )
    monkeypatch.setattr(server, "installed_profile", lambda: profile)

    class Secret:
        def __init__(self, path):
            pass

        def read_text(self):
            return "fixture-token"

    monkeypatch.setattr(server, "Path", Secret)
    started = threading.Event()
    release = threading.Event()
    order = []

    class FakeRuntime:
        def encode(self, kind, content, title, query, configuration):
            order.append(content)
            if content == "first":
                started.set()
                assert release.wait(10)
            return {
                "profile": (configuration or profile).fingerprint,
                "units": 1,
                "parts": [
                    {
                        "start_unit": 0,
                        "end_unit": 1,
                        "tokens": 1,
                        "vector": [1.0] + [0.0] * 767,
                    }
                ],
            }

    monkeypatch.setattr(runtime, "Runtime", FakeRuntime)
    headers = {"Authorization": "Bearer fixture-token"}

    def body(content, query=False):
        return {
            "kind": "text",
            "content": content,
            "query": query,
            "profile": profile.fingerprint,
        }

    with TestClient(server.app) as client:
        assert client.post("/encode", json=body("private")).status_code == 401
        wrong = body("test")
        wrong["profile"] = "d" * 64
        assert client.post("/encode", json=wrong, headers=headers).status_code == 409
        assert (
            client.post(
                "/encode",
                content=b"{}",
                headers=dict(headers, **{"Content-Length": str(33 * 1024**2)}),
            ).status_code
            == 413
        )
        variant = profile.model_copy(
            update={"query_prompt": "task: search result | query: relevant {query}"}
        )
        payload = body("variant")
        payload.update(profile=variant.fingerprint, configuration=variant.model_dump())
        assert (
            client.post("/encode", json=payload, headers=headers).json()["profile"]
            == variant.fingerprint
        )
        image_query = body("image-fixture", True) | {"kind": "image"}
        assert client.post("/encode", json=image_query, headers=headers).status_code == 200
        assert client.post("/encode", json=image_query | {"kind":"video"}, headers=headers).status_code == 422
        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(
                client.post, "/encode", json=body("first"), headers=headers
            )
            assert started.wait(5)
            corpus = pool.submit(
                client.post, "/encode", json=body("corpus"), headers=headers
            )
            query = pool.submit(
                client.post, "/encode", json=body("query", True), headers=headers
            )
            until = time.monotonic() + 5
            while (
                client.get("/health").json()["queued"] < 2 and time.monotonic() < until
            ):
                time.sleep(0.02)
            assert client.get("/health").json()["queued"] == 2
            release.set()
            assert (
                first.result().status_code
                == corpus.result().status_code
                == query.result().status_code
                == 200
            )
        assert order[-3:] == ["first", "query", "corpus"]
