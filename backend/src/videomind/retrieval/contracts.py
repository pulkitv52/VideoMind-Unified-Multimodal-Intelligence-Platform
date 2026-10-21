from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from videomind.contracts import AssetRef, Contract, NonEmpty, Sha256
from videomind.evidence.contracts import Citation
from videomind.preprocessing.contracts import Representation


class DateFilter(Contract):
    field: Literal["source_created", "source_modified", "ingested"]
    after: AwareDatetime | None = None
    before: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.after is None and self.before is None:
            raise ValueError("date filter requires a bound")
        if (
            self.after is not None
            and self.before is not None
            and self.after >= self.before
        ):
            raise ValueError("date range must be nonempty")
        return self


class MediaInterval(Contract):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("media interval must be nonempty")
        return self


class SearchFilters(Contract):
    source_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    asset_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    modalities: tuple[Literal["document", "image", "video", "audio"], ...] = Field(
        default=(), max_length=4
    )
    representations: tuple[Representation, ...] = Field(default=(), max_length=6)
    languages: tuple[NonEmpty, ...] = Field(default=(), max_length=20)
    tags: tuple[NonEmpty, ...] = Field(default=(), max_length=20)
    date: DateFilter | None = None
    media_interval: MediaInterval | None = None


class SearchRequest(Contract):
    workspace_id: UUID
    query: str = Field(min_length=1, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=30)
    strategy: Literal["unified", "per_modality"] = "unified"
    mode: Literal["hybrid", "dense", "lexical", "derived_dense"] = "hybrid"

    @model_validator(mode="after")
    def nonblank_query(self):
        if not self.query.strip():
            raise ValueError("query must contain non-whitespace text")
        return self


class ContextEvidence(Contract):
    segment_id: UUID
    representation: Representation
    snippet: str | None
    citations: tuple[Citation, ...]


class BranchTrace(Contract):
    rank: int = Field(ge=1)
    score: float
    segment_id: UUID


class EvidenceResult(Contract):
    title: str = ""
    source_name: str = ""
    modality: str = ""
    matched_representations: tuple[Representation, ...] = Field(
        default=(), max_length=6
    )
    branches: dict[str, BranchTrace] = Field(default_factory=dict)
    context: tuple[ContextEvidence, ...] = ()
    asset: AssetRef
    segment_id: UUID
    representation: Representation
    citations: tuple[Citation, ...] = Field(min_length=1)
    snippet: NonEmpty | None = None
    dense_score: float | None = Field(default=None, ge=-1, le=1)
    lexical_score: float | None = Field(default=None, ge=0)
    fusion_score: float = Field(ge=0)
    warnings: tuple[NonEmpty, ...] = ()

    @model_validator(mode="after")
    def same_revision(self):
        if any(
            citation.anchor.asset != self.asset for citation in self.citations
        ) or any(
            c.anchor.asset != self.asset
            for item in self.context
            for c in item.citations
        ):
            raise ValueError("result citations must belong to its asset revision")
        return self


class SearchResponse(Contract):
    request_id: UUID
    workspace_id: UUID
    generation_id: UUID
    retrieval_config_sha256: Sha256
    results: tuple[EvidenceResult, ...]
    no_useful_evidence: bool
    profile: str = ""
    configuration: dict = Field(default_factory=dict)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    progress: dict[str, int] = Field(default_factory=dict)
    facets: tuple[dict, ...] = ()
    warnings: tuple[str, ...] = ()
    timings_ms: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def response_scope(self):
        if self.no_useful_evidence and self.results:
            raise ValueError("abstaining responses cannot contain accepted results")
        if any(
            citation.anchor.asset.workspace_id != self.workspace_id
            for result in self.results
            for citation in result.citations
        ):
            raise ValueError("search response cannot cross workspace boundaries")
        return self


class ImageSearchRequest(Contract):
    workspace_id: UUID
    image_base64: str = Field(min_length=1, max_length=5592408)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=30)
    strategy: Literal["unified", "per_modality"] = "unified"
    query: Literal[""] = ""
    mode: Literal["dense"] = "dense"
    query_kind: Literal["image"] = "image"
