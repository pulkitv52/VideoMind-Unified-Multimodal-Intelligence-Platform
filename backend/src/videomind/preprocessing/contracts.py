from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from videomind.contracts import AssetRef, Contract, NonEmpty, Sha256
from videomind.evidence.contracts import EvidenceAnchor

Representation = Literal["text", "ocr", "transcript", "image", "video", "audio"]


class Segment(Contract):
    id: UUID
    asset: AssetRef
    segment_set_id: UUID
    representation: Representation
    ordinal: int = Field(ge=0)
    producer: NonEmpty
    preprocessing_hash: Sha256
    evidence: tuple[EvidenceAnchor, ...] = Field(min_length=1)
    text: NonEmpty | None = None
    language: NonEmpty | None = None
    derived_object_id: UUID | None = None

    @model_validator(mode="after")
    def evidence_and_payload(self):
        if any(anchor.asset != self.asset for anchor in self.evidence):
            raise ValueError("segment evidence must belong to its asset revision")
        if self.representation in {"text", "ocr", "transcript"}:
            if self.text is None:
                raise ValueError("text representations require text")
        elif self.derived_object_id is None:
            raise ValueError("native media representations require an input object")
        return self
