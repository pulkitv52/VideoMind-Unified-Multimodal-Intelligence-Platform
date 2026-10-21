"""Bounded file snapshots shared by the two local connector adapters."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from videomind.connectors.contracts import ConnectorItem, ItemPermissions
from videomind.connectors.upload.validation import InvalidFile, inspect

CHUNK = 1024 * 1024


def stamp(stream):
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def snapshot(stream, workspace, source, external, name, maximum):
    before = stamp(stream)
    if before[2] > maximum:
        raise InvalidFile("FILE_TOO_LARGE")
    mime, _ = inspect(Path(f"/proc/self/fd/{stream.fileno()}"), name)
    stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK):
        size += len(chunk)
        if size > maximum:
            raise InvalidFile("FILE_TOO_LARGE")
        digest.update(chunk)
    if before != stamp(stream) or size != before[2]:
        raise InvalidFile("SOURCE_CHANGED_DURING_READ")
    sha = digest.hexdigest()
    return ConnectorItem(
        workspace_id=workspace,
        source_id=source,
        external_id=external,
        operation="upsert",
        external_revision=sha,
        name=name,
        mime_type=mime,
        size_bytes=size,
        sha256=sha,
        source_modified_at=datetime.fromtimestamp(before[3] / 1e9, timezone.utc),
        permissions=ItemPermissions(state="inherit_source"),
    )


async def stream_revision(stream, item):
    before = stamp(stream)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK):
        size += len(chunk)
        if size > item.size_bytes:
            raise InvalidFile("SOURCE_REVISION_UNAVAILABLE")
        digest.update(chunk)
        yield chunk
    if (
        size != item.size_bytes
        or digest.hexdigest() != item.sha256
        or stamp(stream) != before
    ):
        raise InvalidFile("SOURCE_REVISION_UNAVAILABLE")
