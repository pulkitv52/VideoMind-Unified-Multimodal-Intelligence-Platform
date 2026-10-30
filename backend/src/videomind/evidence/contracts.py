from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from videomind.contracts import AssetRef, Contract, NonEmpty


class PageLocator(Contract):
    kind: Literal["page"] = "page"
    page: int = Field(ge=1)
    # Normalized x0, y0, x1, y1 in the named rendering's coordinate space.
    box: tuple[float, float, float, float] | None = None
    rotation: Literal[0, 90, 180, 270] = 0
    rendering_object_id: UUID | None = None
    transform_id: UUID | None = None

    @model_validator(mode="after")
    def valid_box(self):
        if self.box is not None:
            x0, y0, x1, y1 = self.box
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("box must be nonempty and normalized")
        return self


class TemporalLocator(Contract):
    kind: Literal["temporal"] = "temporal"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    track: NonEmpty
    transform_id: UUID | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("half-open interval must have positive duration")
        return self


class TextLocator(Contract):
    kind: Literal["text"] = "text"
    text_artifact_id: UUID
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_span(self):
        if self.end_char <= self.start_char:
            raise ValueError("Unicode code-point span must be nonempty")
        return self


Locator = Annotated[
    PageLocator | TemporalLocator | TextLocator, Field(discriminator="kind")
]


class EvidenceAnchor(Contract):
    id: UUID
    asset: AssetRef
    original_object_id: UUID
    locator: Locator


class Citation(Contract):
    id: UUID
    anchor: EvidenceAnchor


class ViewerDescriptor(Contract):
    """Returned only after current authorization; this value is not a capability."""

    citation: Citation
    media_type: Literal["document", "image", "video", "audio", "text"]
    stream_object_id: UUID
    is_derivative: bool
    transform_id: UUID | None = None

    @model_validator(mode="after")
    def derivative_mapping(self):
        if self.is_derivative and self.transform_id is None:
            raise ValueError("derivative viewers require an original mapping")
        return self


class Preview(Contract):
    """Metadata for an existing protected image, never a storage capability."""

    kind: Literal["page", "image", "frame"]
    object_id: UUID
    segment_set_id: UUID
    route: Literal["document", "media"]
