"""One immutable upload receipt; changes arrive through explicit submissions."""

from videomind.connectors.contracts import ConnectorCapabilities, DiscoveryPage
from videomind.connectors.files import snapshot, stream_revision
from videomind.connectors.upload.validation import InvalidFile


class UploadConnector:
    connector_id = "upload"
    connector_version = "v1"

    def __init__(self, path, name, workspace, source, maximum=64 * 1024**2):
        self.path, self.name, self.workspace, self.source, self.maximum = (
            path,
            name,
            workspace,
            source,
            maximum,
        )

    def validate_config(self, config):
        if config:
            raise InvalidFile("INVALID_CONNECTOR_CONFIG")
        return {}

    async def capabilities(self):
        return ConnectorCapabilities(
            incremental_sync=False, item_acl=False, deletion_discovery=False
        )

    async def discover(self, cursor):
        if cursor is not None:
            raise InvalidFile("INVALID_CONNECTOR_CURSOR")
        with self.path.open("rb") as stream:
            item = snapshot(
                stream, self.workspace, self.source, self.name, self.name, self.maximum
            )
        # The browser supplies bytes and a name, not the original file's mtime.
        # Quarantine-copy timestamps are receipt times, not source timestamps.
        item = item.model_copy(update={"source_modified_at": None})
        return DiscoveryPage(items=(item,), complete=True)

    async def fetch(self, item):
        if (
            item.workspace_id != self.workspace
            or item.source_id != self.source
            or item.external_id != self.name
        ):
            raise InvalidFile("INVALID_CONNECTOR_ITEM")
        with self.path.open("rb") as stream:
            async for chunk in stream_revision(stream, item):
                yield chunk
