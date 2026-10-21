import hashlib
import json
from pathlib import Path

import pytest
from operations.recovery import CHECK, SNAPSHOT, verify


def test_backup_checks_database_objects_and_journal(tmp_path):
    (tmp_path / "objects").mkdir()
    original = b"original retained bytes"
    digest = hashlib.sha256(original).hexdigest()
    (tmp_path / "objects" / digest).write_bytes(original)
    (tmp_path / "database.dump").write_bytes(b"dump")
    (tmp_path / "journal.json").write_bytes(b"{}")
    manifest = {
        "status": "complete",
        "dump_sha256": hashlib.sha256(b"dump").hexdigest(),
        "journal_sha256": hashlib.sha256(b"{}").hexdigest(),
        "inventory": [{"sha256": digest, "size_bytes": len(original)}],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert verify(tmp_path) == manifest
    (tmp_path / "objects" / digest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Object"):
        verify(tmp_path)
    (tmp_path / "objects" / digest).write_bytes(original)
    (tmp_path / "database.dump").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Database"):
        verify(tmp_path)


def test_embedded_recovery_scripts_compile_and_snapshot_is_exported():
    compile(CHECK, "restore-check", "exec")
    compile(SNAPSHOT, "snapshot", "exec")
    assert "pg_export_snapshot" in SNAPSHOT
    assert "REPEATABLE READ" in SNAPSHOT
    assert "Disposable database required" in CHECK


def test_offline_journal_export_never_invokes_database_sync(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from operations.recovery import journal_export

    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=b'{"lineage":"test","events":[]}')

    monkeypatch.setattr("operations.recovery.subprocess.run", run)
    assert journal_export(tmp_path, fresh=False)["lineage"] == "test"
    invocation = commands[0]
    assert invocation[-2] == "-c"
    assert "sync(" not in invocation[-1]
    assert "export(" in invocation[-1]
