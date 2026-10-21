import math
from uuid import uuid4

import pytest
from pydantic import ValidationError

from videomind.contracts import AssetRef
from videomind.embeddings.contracts import EmbeddingProfile, validate_vector
from videomind.evidence.contracts import (
    Citation,
    EvidenceAnchor,
    PageLocator,
    TemporalLocator,
    TextLocator,
)
from videomind.ingestion.contracts import PublicationManifest
from videomind.preprocessing.contracts import Segment
from videomind.retrieval.contracts import (
    DateFilter,
    EvidenceResult,
    SearchRequest,
    SearchResponse,
)


def test_date_filter_requires_timezone_and_ordered_bounds():
    for values in (
        {"after": "2026-10-16T12:00:00"},
        {"after": "2026-10-17T12:00:00Z", "before": "2026-10-16T12:00:00Z"},
        {},
    ):
        with pytest.raises(ValidationError):
            DateFilter(field="ingested", **values)


def asset():
    return AssetRef(
        **{
            key: uuid4()
            for key in ("workspace_id", "source_id", "asset_id", "revision_id")
        }
    )


def segment():
    ref = asset()
    anchor = EvidenceAnchor(
        id=uuid4(),
        asset=ref,
        original_object_id=uuid4(),
        locator=TemporalLocator(start_ms=200, end_ms=1200, track="audio:0"),
    )
    return Segment(
        id=uuid4(),
        asset=ref,
        segment_set_id=uuid4(),
        representation="audio",
        ordinal=0,
        producer="fixture-v1",
        preprocessing_hash="a" * 64,
        evidence=(anchor,),
        derived_object_id=uuid4(),
    )


@pytest.mark.parametrize(
    "factory,kwargs",
    [
        (TemporalLocator, {"start_ms": 1000, "end_ms": 1000, "track": "audio:0"}),
        (TemporalLocator, {"start_ms": -1, "end_ms": 1000, "track": "audio:0"}),
        (PageLocator, {"page": 0}),
        (PageLocator, {"page": 1, "box": (0.8, 0, 0.2, 1)}),
        (PageLocator, {"page": 1, "box": (0, 0, math.nan, 1)}),
        (TextLocator, {"text_artifact_id": uuid4(), "start_char": 10, "end_char": 5}),
    ],
)
def test_rejects_invalid_evidence_bounds(factory, kwargs):
    with pytest.raises(ValidationError):
        factory(**kwargs)


def test_segment_cannot_attach_other_workspace_evidence():
    original = segment()
    with pytest.raises(ValidationError, match="asset revision"):
        Segment(**{**original.model_dump(), "asset": asset()})


@pytest.mark.parametrize(
    "mutation", ["missing_embedding", "duplicate", "other_revision", "missing_modality"]
)
def test_publication_requires_complete_consistent_coverage(mutation):
    item = segment()
    data = dict(
        asset=item.asset,
        generation_id=uuid4(),
        embedding_profile_sha256="b" * 64,
        segment_set_id=item.segment_set_id,
        segments=(item,),
        embedded_segment_ids=(item.id,),
        required_representations=("audio",),
    )
    if mutation == "missing_embedding":
        data["embedded_segment_ids"] = ()
    elif mutation == "duplicate":
        data["segments"] = (item, item)
    elif mutation == "other_revision":
        data["asset"] = asset()
    else:
        data["required_representations"] = ("audio", "transcript")
    with pytest.raises(ValidationError):
        PublicationManifest(**data)


def test_valid_publication_roundtrips_without_losing_anchor():
    item = segment()
    manifest = PublicationManifest(
        asset=item.asset,
        generation_id=uuid4(),
        embedding_profile_sha256="b" * 64,
        segment_set_id=item.segment_set_id,
        segments=(item,),
        embedded_segment_ids=(item.id,),
        required_representations=("audio",),
    )
    assert (
        PublicationManifest.model_validate_json(manifest.model_dump_json()) == manifest
    )


@pytest.mark.parametrize(
    "values", [[0.0] * 768, [math.nan] * 768, [1.0] * 512, [math.inf] * 768]
)
def test_invalid_vectors_cannot_be_published(values):
    with pytest.raises(ValueError):
        validate_vector(values)


def test_unit_vector_is_valid():
    validate_vector([1 / math.sqrt(768)] * 768)


def test_embedding_profile_requires_pinned_revisions_and_safe_precision():
    data = dict(
        model_revision="a" * 40,
        processor_revision="a" * 40,
        runtime_lock_sha256="b" * 64,
        input_adapter="phase0-v1",
        preprocessing_hash="c" * 64,
    )
    original = EmbeddingProfile(**data)
    assert (
        original.fingerprint != EmbeddingProfile(**{**data, "video_fps": 2}).fingerprint
    )
    for change in ({"model_revision": "main"}, {"precision": "float16"}):
        with pytest.raises(ValidationError):
            EmbeddingProfile(**{**data, **change})


def test_search_response_rejects_cross_workspace_citation():
    item = segment()
    result = EvidenceResult(
        asset=item.asset,
        segment_id=item.id,
        representation="audio",
        fusion_score=0.01,
        citations=(Citation(id=uuid4(), anchor=item.evidence[0]),),
    )
    with pytest.raises(ValidationError, match="workspace"):
        SearchResponse(
            request_id=uuid4(),
            workspace_id=uuid4(),
            generation_id=uuid4(),
            retrieval_config_sha256="a" * 64,
            results=(result,),
            no_useful_evidence=False,
        )


@pytest.mark.parametrize(
    "extra", [{"query": "   "}, {"top_k": 101}, {"filters": {"admin": True}}]
)
def test_search_rejects_bad_input_and_unknown_filters(extra):
    with pytest.raises(ValidationError):
        SearchRequest(**{"workspace_id": uuid4(), "query": "safety", **extra})
