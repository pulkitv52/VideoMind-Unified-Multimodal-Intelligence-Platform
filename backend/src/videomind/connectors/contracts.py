from collections.abc import AsyncIterator
from typing import Literal, Protocol
from uuid import UUID
from datetime import datetime

from pydantic import Field, model_validator

from videomind.contracts import Contract, NonEmpty, Sha256


class ConnectorCapabilities(Contract):
    incremental_sync: bool
    item_acl: bool
    deletion_discovery: bool


class ItemPermissions(Contract):
    state: Literal["inherit_source", "restricted", "unknown"]
    readers: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def valid_readers(self):
        if self.state != "restricted" and self.readers:
            raise ValueError("readers require restricted permissions")
        return self


class ConnectorItem(Contract):
    connector_version: NonEmpty = "v1"
    source_created_at: datetime | None = None
    source_modified_at: datetime | None = None
    workspace_id: UUID
    source_id: UUID
    external_id: NonEmpty
    operation: Literal["upsert", "delete"]
    external_revision: NonEmpty | None = None
    name: NonEmpty | None = None
    mime_type: NonEmpty | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: Sha256 | None = None
    permissions: ItemPermissions

    @model_validator(mode="after")
    def upsert_metadata(self):
        if self.operation == "upsert" and (
            self.external_revision is None or self.mime_type is None
        ):
            raise ValueError("upserts require revision and MIME type")
        return self


class DiscoveryPage(Contract):
    items: tuple[ConnectorItem, ...]
    next_cursor: NonEmpty | None = None
    complete: bool


class Connector(Protocol):
    """Provider implementations perform I/O; ingestion owns durable cursor commits.

    Unknown item ACLs must fail closed. Restricted ACLs with no readers deny all.
    Streaming fetch must yield bytes for the requested immutable revision or fail.
    """

    def validate_config(self, config: dict) -> dict: ...

    async def capabilities(self) -> ConnectorCapabilities: ...

    async def discover(self, cursor: str | None) -> DiscoveryPage: ...

    def fetch(self, item: ConnectorItem) -> AsyncIterator[bytes]: ...
