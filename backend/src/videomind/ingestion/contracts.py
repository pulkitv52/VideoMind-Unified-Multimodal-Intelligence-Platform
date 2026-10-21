from uuid import UUID

from pydantic import Field, model_validator

from videomind.contracts import AssetRef, Contract, NonEmpty, Sha256
from videomind.preprocessing.contracts import Representation, Segment


class PublicationManifest(Contract):
    asset: AssetRef
    generation_id: UUID
    embedding_profile_sha256: Sha256
    segment_set_id: UUID
    segments: tuple[Segment, ...] = Field(min_length=1)
    embedded_segment_ids: tuple[UUID, ...]
    required_representations: tuple[Representation, ...] = Field(min_length=1)
    warnings: tuple[NonEmpty, ...] = ()

    @model_validator(mode="after")
    def complete_generation(self):
        ids = [segment.id for segment in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate segments")
        if len(set(self.embedded_segment_ids)) != len(self.embedded_segment_ids):
            raise ValueError("duplicate embedding coverage entries")
        if set(ids) != set(self.embedded_segment_ids):
            raise ValueError("all published segments require embedding coverage")
        if any(
            segment.asset != self.asset or segment.segment_set_id != self.segment_set_id
            for segment in self.segments
        ):
            raise ValueError("publication cannot mix revisions or segment sets")
        present = {segment.representation for segment in self.segments}
        if not set(self.required_representations) <= present:
            raise ValueError("essential representation is missing")
        return self
