import hashlib
import math
from typing import Literal

from pydantic import Field, model_validator

from videomind.contracts import Contract, NonEmpty, Revision, Sha256


class EmbeddingProfile(Contract):
    model_id: Literal["google/embeddinggemma-2"] = "google/embeddinggemma-2"
    model_revision: Revision
    processor_revision: Revision
    runtime_lock_sha256: Sha256
    dimension: Literal[768] = 768
    precision: Literal["float32", "bfloat16"] = "float32"
    normalize: Literal[True] = True
    pooling: Literal["model_default_mean"] = "model_default_mean"
    query_prompt: NonEmpty = "task: search result | query: {query}"
    document_prompt: NonEmpty = "title: {title} | text: {content}"
    video_fps: float = Field(default=1.0, gt=0, le=30)
    audio_sample_rate: Literal[16000] = 16000
    input_adapter: NonEmpty
    preprocessing_hash: Sha256
    active_encoders: tuple[Literal["text", "vision", "audio"], ...] = (
        "text",
        "vision",
        "audio",
    )

    @model_validator(mode="after")
    def encoders(self):
        if "text" not in self.active_encoders or len(set(self.active_encoders)) != len(
            self.active_encoders
        ):
            raise ValueError("unique encoders including text are required")
        return self

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def validate_vector(values: list[float], dimension: int = 768) -> None:
    if len(values) != dimension:
        raise ValueError(f"expected {dimension} components")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("vector contains nonfinite components")
    norm = math.sqrt(math.fsum(value * value for value in values))
    if abs(norm - 1.0) > 1e-3:
        raise ValueError("vector must have unit L2 norm")


def validate_result(result: dict, fingerprint: str) -> None:
    """Reject incomplete partitions before any vector reaches durable storage."""
    if result.get("profile") != fingerprint:
        raise ValueError("incompatible embedding profile")
    parts = result.get("parts", [])
    units = result.get("units", 0)
    if type(units) is not int or units < 1 or not 1 <= len(parts) <= 64:
        raise ValueError("invalid unit coverage")
    offset = 0
    for part in parts:
        a, b, t = part["start_unit"], part["end_unit"], part["tokens"]
        if (
            any(type(v) is not int for v in (a, b, t))
            or a != offset
            or b <= a
            or not 1 <= t <= 7500
        ):
            raise ValueError("invalid processor partition")
        validate_vector(part["vector"])
        offset = b
    if offset != units:
        raise ValueError("incomplete unit coverage")


def validate_prompts(profile: EmbeddingProfile) -> None:
    """Allow literal retrieval templates, with bounded substitution only."""
    from string import Formatter

    for value, allowed, required in (
        (profile.query_prompt, {"query"}, "query"),
        (profile.document_prompt, {"title", "content"}, "content"),
    ):
        fields = []
        if len(value) > 600:
            raise ValueError("prompt length")
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None:
                if name not in allowed or spec or conversion:
                    raise ValueError("prompt substitutions")
                fields.append(name)
        if fields.count(required) != 1:
            raise ValueError("prompt content placeholder")
