"""Search API tested with actual runtime-role PostgreSQL; deterministic query vectors."""

import json
import os
import time
from uuid import uuid4
from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from test_foundation import foundation, insert
from test_embedding_lifecycle import indexed, build, store, finish
from videomind.embeddings import generations
from videomind.embeddings.client import Client
from videomind.infrastructure.database import transaction

pytestmark = pytest.mark.skipif(
    not os.getenv("VM_MIGRATION_DATABASE_URL"),
    reason="run through scripts/dev.py verify",
)
VECTOR = [1.0] + [0.0] * 767


@pytest.fixture
def searchable(indexed, foundation, monkeypatch):
    f = indexed
    with f["owner"].begin() as c:
        c.execute(
            text(
                "UPDATE app.assets SET title='UNIT-42/A',tags='[\"safety\",\"fixture\"]',source_modified_at='2026-10-10T12:00:00Z' WHERE id=:a"
            ),
            {"a": f["a"]},
        )
        c.execute(
            text(
                "INSERT INTO app.searchable_text(workspace_id,source_id,segment_id,text_content,lexemes) VALUES (:w,:s,:id,'Safety instructions for UNIT-42/A',to_tsvector('simple','Safety instructions for UNIT-42/A'))"
            ),
            {"w": f["w"], "s": f["s"], "id": f["seg"]},
        )
    g, j, p = build(f)
    store(f, j, p)
    finish(f, j)
    with transaction(f["runtime"], f["actor"]) as c:
        generations.promote(c, f["w"], g)
    f.update(g=g, p=p)
    from contextlib import ExitStack
    from fastapi.testclient import TestClient
    from videomind.main import create_app

    _, _, _, _, names, password = foundation
    monkeypatch.setattr(
        Client,
        "encode",
        lambda self, *args, **kwargs: dict(parts=[dict(vector=VECTOR)]),
    )
    original_clients = f["clients"]
    with ExitStack() as stack:
        f["clients"] = {
            name: stack.enter_context(TestClient(create_app())) for name in names
        }
        for name, client in f["clients"].items():
            for cookie in original_clients[name].cookies.jar:
                client.cookies.set(cookie.name, cookie.value)
        yield f
    f["clients"] = original_clients


def request(f, client="alice", wait_for_cpu=True, **patch):
    body = dict(workspace_id=str(f["w"]), query="safety") | patch
    # The live worker also processes other modules' disposable inputs. These
    # tests check retrieval semantics, not concurrent capacity or latency.
    deadline = time.monotonic() + 60
    while True:
        response = f["clients"][client].post(
            f"/api/workspaces/{f['w']}/search", json=body
        )
        if (
            not wait_for_cpu
            or response.status_code != 503
            or response.json().get("detail")
            != "CPU processing is busy; try search again shortly"
            or time.monotonic() >= deadline
        ):
            return response
        time.sleep(0.25)


def test_hybrid_provenance_citations_and_experiments(searchable):
    f = searchable
    for mode in ("hybrid", "dense", "lexical", "derived_dense"):
        for strategy in ("unified", "per_modality"):
            r = request(f, mode=mode, strategy=strategy)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["request_id"] == r.headers["x-request-id"]
            hit = data["results"][0]
            assert (
                data["generation_id"] == str(f["g"])
                and len(data["retrieval_config_sha256"]) == 64
            )
            assert hit["asset"]["revision_id"] == str(f["r"])
            assert hit["matched_representations"] == ["text"]
            if mode == "hybrid":
                assert {"dense", "lexical"} <= set(hit["branches"])
            cite = hit["citations"][0]["id"]
            response = f["clients"]["alice"].get(
                f"/api/workspaces/{f['w']}/sources/{f['s']}/citations/{cite}"
            )
            assert response.status_code == 200
            assert response.json()["revision_id"] == str(f["r"])
    assert (
        "identifier" in request(f, query="UNIT-42/A").json()["results"][0]["branches"]
    )
    assert request(f, mode="lexical", query="xxxxxxxx").json()["no_useful_evidence"]


@pytest.mark.parametrize(
    "filters,expected",
    [
        (
            {
                "modalities": ["document"],
                "representations": ["text"],
                "tags": ["safety", "fixture"],
                "languages": ["und"],
            },
            True,
        ),
        ({"modalities": ["video"]}, False),
        ({"representations": ["audio"]}, False),
        ({"languages": ["en"]}, False),
        ({"tags": ["absent"]}, False),
        (
            {
                "date": {
                    "field": "source_modified",
                    "after": "2026-10-10T00:00:00Z",
                    "before": "2026-10-11T00:00:00Z",
                }
            },
            True,
        ),
        (
            {"date": {"field": "source_modified", "before": "2026-10-10T00:00:00Z"}},
            False,
        ),
        ({"date": {"field": "source_created", "after": "2000-01-01T00:00:00Z"}}, False),
        ({"date": {"field": "ingested", "after": "2000-01-01T00:00:00Z"}}, True),
        ({"media_interval": {"start_ms": 0, "end_ms": 1000}}, False),
    ],
)
def test_filter_semantics_every_branch(searchable, filters, expected):
    f = searchable
    for mode in ("hybrid", "dense", "lexical"):
        r = request(f, filters=filters, mode=mode)
        assert r.status_code == 200, r.text
        assert bool(r.json()["results"]) == expected
        assert bool(r.json()["facets"]) == expected


def test_guessed_ids_and_no_cross_workspace(searchable):
    f = searchable
    for filters in ({"source_ids": [str(uuid4())]}, {"asset_ids": [str(uuid4())]}):
        data = request(f, filters=filters).json()
        assert not data["results"] and not data["facets"]
    assert request(f, workspace_id=str(uuid4())).status_code == 422
    assert f["clients"]["alice"].post(
        f"/api/workspaces/{uuid4()}/search",
        json={"workspace_id": str(uuid4()), "query": "safety"},
    ).status_code in (404, 422)
    r = request(f, client="bob")
    assert r.status_code == 200
    assert not r.json()["results"] and not r.json()["facets"]
    assert (
        f["clients"]["bob"]
        .get(f"/api/workspaces/{f['w']}/search/facets")
        .json()["items"]
        == []
    )


def test_live_grant_revocation_and_mid_request_recheck(searchable, monkeypatch):
    f = searchable
    with f["owner"].begin() as c:
        insert(
            c,
            "app.source_grants",
            workspace_id=f["w"],
            source_id=f["s"],
            principal_id=f["bob"],
            permission="read",
        )
    assert request(f, client="bob").json()["results"]

    def encode(self, *args, **kwargs):
        with f["owner"].begin() as c:
            c.execute(
                text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": f["s"]}
            )
        return dict(parts=[dict(vector=VECTOR)])

    monkeypatch.setattr(Client, "encode", encode)
    data = request(f, client="bob").json()
    assert data["results"] == [] and data["facets"] == []
    assert request(f, client="bob", mode="lexical").json()["results"] == []


def test_tombstone_abstention_and_model_failure(searchable, monkeypatch):
    f = searchable
    monkeypatch.setattr(
        Client,
        "encode",
        lambda *args, **kwargs: dict(parts=[dict(vector=[-1.0] + [0.0] * 767)]),
    )
    assert request(f, query="unrelated", mode="dense").json()["no_useful_evidence"]

    def broken(*args, **kwargs):
        raise RuntimeError("private exception content")

    monkeypatch.setattr(Client, "encode", broken)
    r = request(f)
    assert r.status_code == 503 and "private exception" not in r.text
    with f["owner"].begin() as c:
        c.execute(text("UPDATE app.assets SET deleted=true WHERE id=:a"), {"a": f["a"]})
    data = request(f, mode="lexical").json()
    assert data["results"] == [] and data["facets"] == []


def test_native_audio_temporal_filter_and_no_text_dependency(searchable):
    f = searchable
    with f["owner"].begin() as c:
        c.execute(
            text("UPDATE app.assets SET modality='audio' WHERE id=:a"), {"a": f["a"]}
        )
        # Only fixture owner mutates immutable facts; production never does this.
        c.execute(text("SET LOCAL session_replication_role='replica'"))
        c.execute(
            text(
                "UPDATE app.segments SET representation='audio',text_content=NULL WHERE id=:s"
            ),
            {"s": f["seg"]},
        )
        c.execute(
            text(
                "UPDATE app.evidence_anchors SET locator_kind='temporal',page=NULL,start_ms=1000,end_ms=5000,track='audio:0' WHERE revision_id=:r"
            ),
            {"r": f["r"]},
        )
        c.execute(
            text("DELETE FROM app.searchable_text WHERE segment_id=:s"), {"s": f["seg"]}
        )
    data = request(
        f,
        query="electronic beeping",
        filters={
            "modalities": ["audio"],
            "media_interval": {"start_ms": 3000, "end_ms": 4000},
        },
    ).json()
    assert (
        data["results"][0]["representation"] == "audio"
        and data["results"][0]["snippet"] is None
    )
    assert data["results"][0]["citations"][0]["anchor"]["locator"]["start_ms"] == 1000
    assert (
        request(
            f, filters={"media_interval": {"start_ms": 5000, "end_ms": 6000}}
        ).json()["results"]
        == []
    )


def test_context_bounded_and_filtered(searchable):
    f = searchable
    with f["owner"].begin() as c:
        for ordinal in range(1, 5):
            segment, anchor = uuid4(), uuid4()
            scope = {"workspace_id": f["w"], "source_id": f["s"]}
            insert(
                c,
                "app.segments",
                **scope,
                id=segment,
                segment_set_id=f["ss"],
                revision_id=f["r"],
                representation="text",
                ordinal=ordinal,
                text_content=f"Context passage {ordinal}",
                producer="fixture",
            )
            obj = c.execute(
                text("SELECT original_object_id FROM app.asset_revisions WHERE id=:r"),
                {"r": f["r"]},
            ).scalar_one()
            insert(
                c,
                "app.evidence_anchors",
                **scope,
                id=anchor,
                revision_id=f["r"],
                original_object_id=obj,
                locator_kind="page",
                page=ordinal + 1,
            )
            insert(
                c,
                "app.segment_evidence",
                **scope,
                segment_id=segment,
                anchor_id=anchor,
                revision_id=f["r"],
                relation="extracted_from",
                producer="fixture",
            )
            insert(
                c, "app.citation_records", **scope, segment_id=segment, anchor_id=anchor
            )
    data = request(f, filters={"asset_ids": [str(f["a"])]}).json()
    hit = data["results"][0]
    assert len(hit["context"]) == 2
    assert {r["snippet"] for r in hit["context"]} == {
        "Context passage 1",
        "Context passage 2",
    }
    assert all(
        c["anchor"]["asset"] == hit["asset"]
        for r in hit["context"]
        for c in r["citations"]
    )
    assert request(f, filters={"representations": ["audio"]}).json()["results"] == []


def test_request_pins_generation_across_cutover(searchable, monkeypatch):
    f = searchable

    def encode(self, *args, **kwargs):
        g, j, p = build(f, "search-new-profile")
        store(f, j, p, [0.0, 1.0] + [0.0] * 766)
        finish(f, j)
        with transaction(f["runtime"], f["actor"]) as c:
            generations.promote(c, f["w"], g)
        return dict(parts=[dict(vector=VECTOR)])

    monkeypatch.setattr(Client, "encode", encode)
    data = request(f).json()
    assert data["generation_id"] == str(f["g"])
    assert data["results"][0]["dense_score"] == pytest.approx(1)


def test_busy_cpu_and_oversized_query_fail_explicitly(searchable, monkeypatch):
    from videomind.embeddings.indexer import heavy
    from urllib.error import HTTPError

    f = searchable
    with heavy(f["runtime"]):
        r = request(f, wait_for_cpu=False)
    assert r.status_code == 503 and "CPU processing" in r.json()["detail"]

    def oversized(*args, **kwargs):
        raise HTTPError("private", 422, "budget", {}, None)

    monkeypatch.setattr(Client, "encode", oversized)
    assert request(f).status_code == 422
    assert request(f, query=" " * 4).status_code == 422
    assert request(f, query="a" * 2001).status_code == 422


def test_final_materialization_rechecks_grants(searchable, monkeypatch):
    from videomind.retrieval import ranking

    f = searchable
    with f["owner"].begin() as c:
        insert(
            c,
            "app.source_grants",
            workspace_id=f["w"],
            source_id=f["s"],
            principal_id=f["bob"],
            permission="read",
        )
    original = ranking.fuse

    def revoked(*args, **kwargs):
        result = original(*args, **kwargs)
        with f["owner"].begin() as c:
            c.execute(
                text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": f["s"]}
            )
        return result

    monkeypatch.setattr(ranking, "fuse", revoked)
    data = request(f, client="bob").json()
    assert data["results"] == [] and data["facets"] == []
    assert data["progress"] == {
        "unpublished_assets": 0,
        "pending_updates": 0,
        "assets_with_errors": 0,
    }


def test_many_result_context_keeps_bounded_queries_and_same_nearest_evidence(
    searchable,
):
    from sqlalchemy import event

    f = searchable
    with f["owner"].begin() as c:
        obj = c.execute(
            text("SELECT original_object_id FROM app.asset_revisions WHERE id=:r"),
            {"r": f["r"]},
        ).scalar_one()
        for ordinal in range(1, 13):
            segment, anchor = uuid4(), uuid4()
            scope = {"workspace_id": f["w"], "source_id": f["s"]}
            insert(
                c,
                "app.segments",
                **scope,
                id=segment,
                segment_set_id=f["ss"],
                revision_id=f["r"],
                representation="text",
                ordinal=ordinal,
                text_content=f"Neighbor {ordinal}",
                producer="fixture",
            )
            insert(
                c,
                "app.evidence_anchors",
                **scope,
                id=anchor,
                revision_id=f["r"],
                original_object_id=obj,
                locator_kind="page",
                page=ordinal + 1,
            )
            insert(
                c,
                "app.segment_evidence",
                **scope,
                segment_id=segment,
                anchor_id=anchor,
                revision_id=f["r"],
                relation="extracted_from",
                producer="fixture",
            )
            insert(
                c, "app.citation_records", **scope, segment_id=segment, anchor_id=anchor
            )
            insert(
                c,
                "app.embeddings",
                **scope,
                segment_id=segment,
                profile_id=f["p"]["profile_id"],
                input_hash="e" * 64,
                embedding=json.dumps(VECTOR),
            )
    engine = f["clients"]["alice"].app.state.db
    calls = []
    preview_calls = []

    def observed(conn, cursor, statement, parameters, context, executemany):
        if "preview_candidates" in statement:
            preview_calls.append(statement)
        if "abs(ordinal" in statement or "abs(s.ordinal" in statement:
            calls.append(statement)

    event.listen(engine, "before_cursor_execute", observed)
    try:
        response = request(
            f, query="UNIT-42/A", top_k=10, filters={"asset_ids": [str(f["a"])]}
        )
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 10
    with f["owner"].connect() as c:
        all_rows = [
            dict(r)
            for r in c.execute(
                text("SELECT id,ordinal FROM app.segments WHERE segment_set_id=:ss"),
                {"ss": f["ss"]},
            ).mappings()
        ]
    for hit in results:
        ordinal = next(
            r["ordinal"] for r in all_rows if str(r["id"]) == hit["segment_id"]
        )
        expected = sorted(
            (r for r in all_rows if str(r["id"]) != hit["segment_id"]),
            key=lambda r: (abs(r["ordinal"] - ordinal), r["ordinal"], str(r["id"])),
        )[:2]
        assert {r["segment_id"] for r in hit["context"]} == {
            str(r["id"]) for r in expected
        }
        assert all(
            cite["anchor"]["asset"] == hit["asset"]
            for row in hit["context"]
            for cite in row["citations"]
        )
    assert (
        len(preview_calls) == 1
    ), "Preview metadata must use one batch for ten results"
    assert (
        len(calls) <= 2
    ), "Context expansion must not repeat the scope query for every result"


def image_request(f, client="alice", **patch):
    import base64, io
    from PIL import Image

    raw = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(raw, format="PNG")
    body = {
        "workspace_id": str(f["w"]),
        "image_base64": base64.b64encode(raw.getvalue()).decode(),
    } | patch
    deadline = time.monotonic() + 60
    while True:
        response = f["clients"][client].post(
            f"/api/workspaces/{f['w']}/search/image", json=body
        )
        if (
            response.status_code != 503
            or response.json().get("detail")
            != "CPU processing is busy; try search again shortly"
            or time.monotonic() >= deadline
        ):
            return response
        time.sleep(0.25)


def test_image_query_reuses_scoped_dense_results_and_never_adds_assets(
    searchable, monkeypatch
):
    import base64, io
    from PIL import Image

    f = searchable
    calls = []

    def encode(self, profile, kind, content, **kwargs):
        assert kind == "image" and kwargs["query"]
        with Image.open(io.BytesIO(base64.b64decode(content))) as image:
            assert image.size == (32, 24)
        calls.append(profile)
        return {"parts": [{"vector": VECTOR}]}

    monkeypatch.setattr(Client, "encode", encode)
    response = image_request(f)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["configuration"]["query_kind"] == "image"
    assert result["results"][0]["asset"]["asset_id"] == str(f["a"])
    assert set(result["results"][0]["branches"]) == {"dense"}
    assert calls
    assert image_request(f, client="carol", image_base64="invalid").status_code == 404
    assert image_request(f, image_base64="invalid!").status_code == 422
    assert image_request(f, mode="hybrid").status_code == 422


def test_image_decoder_strips_exif_and_rejects_unsupported_inputs():
    import base64, io
    from PIL import Image
    from videomind.retrieval.image_query import normalize
    from fastapi import HTTPException

    raw = io.BytesIO()
    image = Image.new("RGB", (32, 24), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private-metadata"
    image.save(raw, format="JPEG", exif=exif)
    decoded = base64.b64decode(normalize(base64.b64encode(raw.getvalue()).decode()))
    with Image.open(io.BytesIO(decoded)) as result:
        assert result.size == (24, 32)
        assert not result.getexif()
        assert b"private-metadata" not in decoded
    for dimensions, fmt in (((3000, 3000), "PNG"), ((32, 24), "GIF")):
        raw = io.BytesIO()
        Image.new("RGB", dimensions).save(raw, format=fmt)
        with pytest.raises(HTTPException) as exc:
            normalize(base64.b64encode(raw.getvalue()).decode())
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        normalize(base64.b64encode(b"not image data").decode())


def test_image_query_rechecks_revocation_during_embedding(searchable, monkeypatch):
    f = searchable
    with f["owner"].begin() as c:
        insert(
            c,
            "app.source_grants",
            workspace_id=f["w"],
            source_id=f["s"],
            principal_id=f["bob"],
            permission="read",
        )

    def encode(*args, **kwargs):
        with f["owner"].begin() as c:
            c.execute(
                text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": f["s"]}
            )
        return {"parts": [{"vector": VECTOR}]}

    monkeypatch.setattr(Client, "encode", encode)
    response = image_request(f, client="bob")
    assert response.status_code == 200, response.text
    assert response.json()["results"] == [] and response.json()["facets"] == []


@pytest.mark.parametrize("kind", ["page", "image", "frame"])
def test_preview_provenance_bounds_and_live_access(searchable, kind):
    """Use the restricted role for metadata and bytes, including old revisions."""
    import io
    from PIL import Image
    from videomind.evidence.previews import resolve_batch
    from videomind.retrieval.contracts import EvidenceResult

    f = searchable
    scope = {"workspace_id": f["w"], "source_id": f["s"]}
    oid = uuid4()
    raw = io.BytesIO()
    Image.new("RGB", (12, 12), "green").save(raw, format="PNG")
    content = raw.getvalue()
    objects = f["clients"]["alice"].app.state.objects
    bucket = f["clients"]["alice"].app.state.settings.minio_bucket
    key = f"fixtures/previews/{oid}"
    objects.put_object(bucket, key, io.BytesIO(content), len(content))
    try:
        with f["owner"].begin() as c:
            insert(
                c,
                "app.objects",
                **scope,
                id=oid,
                bucket=bucket,
                object_key=key,
                sha256="d" * 64,
                size_bytes=len(content),
                mime_type="image/png",
                role="derivative",
            )
            insert(
                c,
                "app.document_pages",
                **scope,
                segment_set_id=f["ss"],
                page=1,
                revision_id=f["r"],
                text_object_id=oid,
                manifest="{}",
                image_object_id=oid,
                width=12,
                height=12,
            )
        route = "media" if kind == "frame" else "document"
        with f["owner"].begin() as c:
            if kind == "image":
                c.execute(
                    text("UPDATE app.assets SET modality='image' WHERE id=:a"),
                    {"a": f["a"]},
                )
            if kind == "frame":
                c.execute(
                    text("UPDATE app.assets SET modality='video' WHERE id=:a"),
                    {"a": f["a"]},
                )
                c.execute(text("SET LOCAL session_replication_role='replica'"))
                c.execute(
                    text(
                        "UPDATE app.segment_sets SET manifest=CAST(:manifest AS jsonb) WHERE id=:ss"
                    ),
                    {"ss": f["ss"], "manifest": json.dumps({"kind": "media"})},
                )
                c.execute(
                    text(
                        "UPDATE app.segments SET representation='video' WHERE id=:seg"
                    ),
                    {"seg": f["seg"]},
                )
                c.execute(
                    text(
                        "UPDATE app.evidence_anchors SET locator_kind='temporal',page=NULL,start_ms=0,end_ms=1000,track='video:0',transform=CAST(:mapping AS jsonb) WHERE revision_id=:r"
                    ),
                    {
                        "r": f["r"],
                        "mapping": json.dumps(
                            {"frames": [{"object_id": str(oid), "original_ms": 0}]}
                        ),
                    },
                )
                insert(
                    c,
                    "app.media_presentations",
                    **scope,
                    segment_set_id=f["ss"],
                    revision_id=f["r"],
                    playback_object_id=oid,
                    mapping_object_id=oid,
                    manifest="{}",
                )
                insert(
                    c,
                    "app.media_artifacts",
                    **scope,
                    segment_set_id=f["ss"],
                    object_id=oid,
                )
        baseline = request(f, mode="lexical").json()["results"][0]
        assert baseline["preview"] == {
            "kind": kind,
            "object_id": str(oid),
            "segment_set_id": str(f["ss"]),
            "route": route,
        }
        path = (
            f"/api/workspaces/{f['w']}/sources/{f['s']}/revisions/{f['r']}"
            f"/{route}/objects/{oid}?segment_set_id={f['ss']}"
        )
        assert f["clients"]["alice"].get(path).content == content
        assert f["clients"]["bob"].get(path).status_code == 404
        # Bounded metadata, with unchanged ordered retrieval facts.
        with f["owner"].begin() as c:
            c.execute(
                text("UPDATE app.objects SET size_bytes=4194305 WHERE id=:id"),
                {"id": oid},
            )
        oversized = request(f, mode="lexical").json()["results"][0]
        assert oversized["preview"] is None
        assert {k: v for k, v in oversized.items() if k != "preview"} == {
            k: v for k, v in baseline.items() if k != "preview"
        }
        with f["owner"].begin() as c:
            c.execute(
                text("UPDATE app.objects SET size_bytes=:n WHERE id=:id"),
                {"id": oid, "n": len(content)},
            )
            insert(
                c,
                "app.source_grants",
                **scope,
                principal_id=f["bob"],
                permission="read",
            )
        hit = EvidenceResult.model_validate(
            request(f, client="bob", mode="lexical").json()["results"][0]
        )
        assert f["clients"]["bob"].get(path).status_code == 200
        with f["owner"].begin() as c:
            c.execute(
                text("DELETE FROM app.source_grants WHERE source_id=:s"), {"s": f["s"]}
            )
        with transaction(f["runtime"], f["bob"]) as c:
            assert resolve_batch(c, f["w"], [hit]) == {}
        assert f["clients"]["bob"].get(path).status_code == 404
        assert (
            f["clients"]["alice"].get(path.replace(str(oid), str(uuid4()))).status_code
            == 404
        )
        assert (
            f["clients"]["alice"]
            .get(path.replace(str(f["ss"]), str(uuid4())))
            .status_code
            == 404
        )
        with f["owner"].begin() as c:
            # A later pending revision must not redirect an existing preview.
            newer = uuid4()
            original = c.execute(
                text("SELECT original_object_id FROM app.asset_revisions WHERE id=:r"),
                {"r": f["r"]},
            ).scalar_one()
            insert(
                c,
                "app.asset_revisions",
                **scope,
                id=newer,
                asset_id=f["a"],
                external_revision="v2",
                sha256="a" * 64,
                original_object_id=original,
            )
            c.execute(
                text("UPDATE app.assets SET latest_revision_id=:r WHERE id=:a"),
                {"r": newer, "a": f["a"]},
            )
        historical = request(f, mode="lexical").json()["results"][0]
        assert historical["asset"]["revision_id"] == str(f["r"])
        assert historical["preview"] == baseline["preview"]
        assert f["clients"]["alice"].get(path).content == content
        with f["owner"].begin() as c:
            c.execute(
                text("UPDATE app.assets SET deleted=true WHERE id=:a"), {"a": f["a"]}
            )
        assert f["clients"]["alice"].get(path).status_code == 404
        assert not request(f, mode="lexical").json()["results"]
    finally:
        objects.remove_object(bucket, key)
