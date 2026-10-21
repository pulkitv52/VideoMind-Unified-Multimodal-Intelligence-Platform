"""Paged, bounded full-manifest discovery. Cursors belong to one scan only."""

import hashlib
import os
from pathlib import PurePosixPath
import stat
import time

from videomind.connectors.contracts import ConnectorCapabilities, DiscoveryPage
from videomind.connectors.files import snapshot, stream_revision
from videomind.connectors.local_folder.reader import files, folder_fd, relative_folder
from videomind.connectors.upload.validation import InvalidFile


class LocalFolderConnector:
    connector_id = "local_folder"
    connector_version = "v1"

    def __init__(
        self, root, config, workspace, source, maximum=64 * 1024**2, page_size=50
    ):
        self.root, self.config, self.workspace, self.source, self.maximum = (
            root,
            self.validate_config(config),
            workspace,
            source,
            maximum,
        )
        self.page_size = page_size
        self.items = None
        self.snapshot_id = None
        self.started = time.monotonic()

    def validate_config(self, config):
        if set(config) != {"folder"} or not isinstance(config["folder"], str):
            raise InvalidFile("INVALID_CONNECTOR_CONFIG")
        return {"folder": relative_folder(config["folder"])}

    async def capabilities(self):
        return ConnectorCapabilities(
            incremental_sync=False, item_acl=False, deletion_discovery=True
        )

    def deadline(self):
        if time.monotonic() - self.started > 180:
            raise InvalidFile("FOLDER_TIME_LIMIT")

    async def discover(self, cursor):
        self.deadline()
        if self.items is None:
            if cursor is not None:
                raise InvalidFile("INVALID_CONNECTOR_CURSOR")
            self.items = []
            total = 0
            for external, name, declared, stream in files(
                self.root, self.config["folder"]
            ):
                self.deadline()
                if declared > 256 * 1024**2 - total:
                    raise InvalidFile("FOLDER_BYTE_LIMIT")
                item = snapshot(
                    stream, self.workspace, self.source, external, name, self.maximum
                )
                total += item.size_bytes
                if total > 256 * 1024**2:
                    raise InvalidFile("FOLDER_BYTE_LIMIT")
                self.items.append(item)
            self.items.sort(key=lambda item: item.external_id)
            material = "\n".join(f"{i.external_id}\0{i.sha256}" for i in self.items)
            self.snapshot_id = hashlib.sha256(material.encode()).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                fingerprint, position = cursor.split(":")
                offset = int(position)
                if (
                    fingerprint != self.snapshot_id
                    or offset < 0
                    or offset >= len(self.items)
                    or offset % self.page_size
                ):
                    raise ValueError
            except (ValueError, AttributeError):
                raise InvalidFile("INVALID_CONNECTOR_CURSOR") from None
        end = offset + self.page_size
        complete = end >= len(self.items)
        return DiscoveryPage(
            items=tuple(self.items[offset:end]),
            next_cursor=None if complete else f"{self.snapshot_id}:{end}",
            complete=complete,
        )

    async def fetch(self, item):
        self.deadline()
        if self.items is None or item not in self.items:
            raise InvalidFile("INVALID_CONNECTOR_ITEM")
        parts = PurePosixPath(item.external_id).parts
        if not parts or ".." in parts or PurePosixPath(item.external_id).is_absolute():
            raise InvalidFile("INVALID_CONNECTOR_ITEM")
        relative = str(
            PurePosixPath(self.config["folder"]) / PurePosixPath(*parts[:-1])
        )
        with folder_fd(self.root, relative) as parent:
            handle = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            with os.fdopen(handle, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise InvalidFile("UNSAFE_FOLDER_ENTRY")
                async for chunk in stream_revision(stream, item):
                    self.deadline()
                    yield chunk
