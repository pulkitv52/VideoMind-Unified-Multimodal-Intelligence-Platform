"""Private credential handling and repeat setup for the optional pgAdmin UI."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "database_viewer", SCRIPTS / "database_viewer.py"
)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def test_pgadmin_setup_preserves_password_and_keeps_it_out_of_shared_metadata(
    tmp_path, monkeypatch
):
    (tmp_path / ".local").mkdir()
    monkeypatch.setattr(viewer, "ROOT", tmp_path)
    original = viewer.prepare_pgadmin()
    assert viewer.prepare_pgadmin() == original
    local = tmp_path / ".local"
    for name in ("pgadmin.json", "pgadmin.env"):
        assert (local / name).stat().st_mode & 0o777 == 0o600
    servers = (local / "pgadmin-servers.json").read_text()
    assert original["password"] not in servers
    assert (
        json.loads(servers)["Servers"]["1"]["ConnectionParameters"]["passfile"]
        == ".pgpass"
    )


def test_invalid_saved_credentials_cannot_inject_environment_settings(
    tmp_path, monkeypatch
):
    local = tmp_path / ".local"
    local.mkdir()
    monkeypatch.setattr(viewer, "ROOT", tmp_path)
    (local / "pgadmin.json").write_text(
        json.dumps({"email": "owner@example.com", "password": "test\nINJECTED=value"})
    )
    with pytest.raises(ValueError):
        viewer.prepare_pgadmin()
    assert not (local / "pgadmin.env").exists()
