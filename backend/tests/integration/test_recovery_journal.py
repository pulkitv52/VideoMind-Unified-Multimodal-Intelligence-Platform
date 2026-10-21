"""Committed tombstone capture and operator-only journal privileges."""

from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_foundation import foundation, insert, pytestmark
from videomind.infrastructure.database import transaction


def test_recovery_events_follow_commit_and_survive_content_removal(foundation):
    ids, owner, runtime, *_ = foundation
    source, asset = uuid4(), uuid4()
    workspace = ids["workspace"]
    with owner.begin() as c:
        insert(
            c,
            "app.sources",
            workspace_id=workspace,
            id=source,
            name="Recovery fixture",
            connector_kind="upload",
        )
        insert(
            c,
            "app.assets",
            workspace_id=workspace,
            source_id=source,
            id=asset,
            external_id="recovery-test",
            title="Recovery fixture",
            modality="document",
            mime_type="text/plain",
        )

    def rows():
        with owner.connect() as c:
            return (
                c.execute(
                    text(
                        "SELECT deleted FROM recovery.events WHERE asset_id=:a ORDER BY sequence"
                    ),
                    {"a": asset},
                )
                .scalars()
                .all()
            )

    try:
        with pytest.raises(RuntimeError):
            with transaction(runtime, ids["alice"]) as c:
                c.execute(
                    text("UPDATE app.assets SET deleted=true WHERE id=:a"), {"a": asset}
                )
                raise RuntimeError("Rollback fixture")
        assert rows() == []
        for deleted in (True, False, False, True):
            with transaction(runtime, ids["alice"]) as c:
                c.execute(
                    text("UPDATE app.assets SET deleted=:deleted WHERE id=:a"),
                    {"a": asset, "deleted": deleted},
                )
        assert rows() == [True, False, True]
        for statement in (
            "SELECT * FROM recovery.events",
            "DELETE FROM recovery.events",
            "SELECT * FROM recovery.identity",
        ):
            with pytest.raises(DBAPIError):
                with transaction(runtime, ids["alice"]) as c:
                    c.execute(text(statement))
    finally:
        with owner.begin() as c:
            c.execute(
                text("DELETE FROM app.sources WHERE workspace_id=:w AND id=:s"),
                {"w": workspace, "s": source},
            )
    assert rows() == [True, False, True, True]


def test_operator_export_recovers_from_failed_file_commit(
    foundation, tmp_path, monkeypatch
):
    from videomind.recovery import journal

    _, owner, *_ = foundation
    path = tmp_path / "journal.sqlite3"
    initial = journal.sync(owner, path)

    def fail(*args):
        raise ValueError("Simulated external journal failure")

    with monkeypatch.context() as patch:
        patch.setattr(journal, "persist", fail)
        with pytest.raises(ValueError, match="Simulated"):
            journal.sync(owner, path)
    again = journal.sync(owner, path)
    assert again["lineage"] == initial["lineage"]
    assert journal.export(path)["lineage"] == initial["lineage"]
    with owner.begin() as c:
        pid = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND objid=814207319"
                ),
                {"pid": pid},
            ).scalar_one()
            == 0
        )
