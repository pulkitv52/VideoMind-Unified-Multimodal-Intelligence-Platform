"""Small shared value types; domain behavior stays in its owning module."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NonEmpty = Annotated[str, Field(min_length=1, max_length=4096)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AssetRef(Contract):
    workspace_id: UUID
    source_id: UUID
    asset_id: UUID
    revision_id: UUID
