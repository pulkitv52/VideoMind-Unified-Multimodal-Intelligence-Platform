import asyncio
from uuid import uuid4

import pytest

from videomind.connectors.local_folder.adapter import LocalFolderConnector
from videomind.connectors.upload.adapter import UploadConnector
from videomind.connectors.upload.validation import InvalidFile


def test_folder_pages_bind_one_manifest_and_fetch_exact_revisions(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.txt").write_text(f"version {i}")
    connector = LocalFolderConnector(
        tmp_path, {"folder": ""}, uuid4(), uuid4(), page_size=2
    )

    async def run():
        caps = await connector.capabilities()
        assert (
            caps.deletion_discovery and not caps.incremental_sync and not caps.item_acl
        )
        first = await connector.discover(None)
        assert len(first.items) == 2 and not first.complete
        final = await connector.discover(first.next_cursor)
        assert len(final.items) == 1 and final.complete and final.next_cursor is None
        item = first.items[0]
        assert b"".join([part async for part in connector.fetch(item)]) == b"version 0"
        (tmp_path / "0.txt").write_text("changed")
        with pytest.raises(InvalidFile, match="SOURCE_REVISION_UNAVAILABLE"):
            [part async for part in connector.fetch(item)]
        other = LocalFolderConnector(
            tmp_path, {"folder": ""}, connector.workspace, connector.source, page_size=2
        )
        await other.discover(None)
        with pytest.raises(InvalidFile, match="INVALID_CONNECTOR_CURSOR"):
            await other.discover(first.next_cursor)

    asyncio.run(run())


def test_upload_receipt_has_no_provider_cursor_and_refuses_wrong_scope(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("original")
    connector = UploadConnector(path, path.name, uuid4(), uuid4())
    assert connector.validate_config({}) == {}

    async def run():
        page = await connector.discover(None)
        assert page.complete
        item = page.items[0]
        assert item.source_modified_at is None
        assert b"".join([part async for part in connector.fetch(item)]) == b"original"
        with pytest.raises(InvalidFile):
            await connector.discover("arbitrary")
        with pytest.raises(InvalidFile):
            [
                part
                async for part in connector.fetch(
                    item.model_copy(update={"source_id": uuid4()})
                )
            ]

    asyncio.run(run())


def test_adapter_config_and_size_budgets_fail_before_fetch(tmp_path):
    (tmp_path / "large.txt").write_text("too large")
    with pytest.raises(InvalidFile):
        LocalFolderConnector(tmp_path, {"folder": "../escape"}, uuid4(), uuid4())
    with pytest.raises(InvalidFile):
        LocalFolderConnector(tmp_path, {"folder": "", "extra": 1}, uuid4(), uuid4())
    connector = LocalFolderConnector(
        tmp_path, {"folder": ""}, uuid4(), uuid4(), maximum=2
    )
    with pytest.raises(InvalidFile, match="FILE_TOO_LARGE"):
        asyncio.run(connector.discover(None))


def test_empty_directory_depth_is_bounded_without_needing_a_file(tmp_path):
    from videomind.connectors.local_folder.reader import files, relative_folder

    deep = tmp_path
    for _ in range(18):
        deep = deep / "child"
        deep.mkdir()
    with pytest.raises(InvalidFile, match="FOLDER_DIRECTORY_LIMIT"):
        list(files(tmp_path, ""))
    with pytest.raises(InvalidFile, match="INVALID_FOLDER"):
        relative_folder("bad\x00folder")


@pytest.mark.parametrize("entry", ["hardlink", "fifo"])
def test_non_regular_or_shared_inode_entries_are_rejected(tmp_path, entry):
    import os
    from videomind.connectors.local_folder.reader import files

    root = tmp_path / "imports"
    root.mkdir()
    if entry == "hardlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("private")
        os.link(outside, root / "linked.txt")
    else:
        os.mkfifo(root / "pipe.txt")
    with pytest.raises(InvalidFile, match="UNSAFE_FOLDER_ENTRY"):
        list(files(root, ""))
