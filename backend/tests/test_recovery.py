import json
import stat

import pytest
from videomind.recovery.journal import export, persist


def event(identity, sequence=1, deleted=True):
    return {
        "event_id": identity,
        "sequence": sequence,
        "kind": "asset",
        "workspace_id": "workspace",
        "source_id": "source",
        "asset_id": "asset",
        "deleted": deleted,
        "recorded_at": "2026-10-20 00:00:00+00:00",
    }


def test_journal_retries_late_commits_and_reinstatements(tmp_path):
    path = tmp_path / "journal.sqlite3"
    newer = event("first", 10)
    persist(path, "lineage", [newer])
    # A lower sequence can commit later for a different entity. Do not skip it.
    late = event("late", 5)
    reinstated = event("reinstate", 11, False)
    persist(path, "lineage", [late, newer, reinstated])
    persist(path, "lineage", [late, newer, reinstated])
    assert [e["event_id"] for e in export(path)["events"]] == [
        "first",
        "late",
        "reinstate",
    ]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="lineage"):
        persist(path, "other-lineage", [])
    assert export(path)["lineage"] == "lineage"


def test_journal_identity_conflict_rolls_back_whole_export(tmp_path):
    path = tmp_path / "journal.sqlite3"
    persist(path, "lineage", [event("one")])
    with pytest.raises(ValueError, match="conflict"):
        persist(path, "lineage", [event("two"), event("one", deleted=False)])
    assert [e["event_id"] for e in export(path)["events"]] == ["one"]
