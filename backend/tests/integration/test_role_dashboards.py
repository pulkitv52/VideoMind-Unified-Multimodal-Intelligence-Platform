"""Restricted-role directory checks and explicit operator provisioning safety."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from test_access import access
from test_foundation import foundation, pytestmark
from videomind.identity import role_demo
from videomind.identity.access import collection_capabilities
from videomind.infrastructure.database import transaction


def test_people_directory_is_admin_only_scoped_paginated_and_secret_free(access):
    f = access
    base = f"/api/workspaces/{f['w']}/people"
    for person in ("alice", "bob"):
        client = f["clients"][person]
        found, cursor = [], None
        for _ in range(3):
            response = client.get(
                base, params={"limit": 1, **({"after": cursor} if cursor else {})}
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            page = response.json()
            found += page["items"]
            cursor = page["next_cursor"]
        assert cursor is None
        assert {row["principal_id"] for row in found} == {
            str(f["ids"][name]) for name in ("alice", "bob", "carol")
        }
        assert {row["role"] for row in found} == {"owner", "admin", "member"}
        assert all(
            set(row)
            == {"principal_id", "username", "role", "disabled", "joined_at", "version"}
            for row in found
        )
        assert client.get(f"/api/workspaces/{uuid4()}/people").status_code == 404
        assert client.get(base, params={"limit": 101}).status_code == 422
    assert f["clients"]["carol"].get(base).status_code == 403
    with transaction(f["runtime"], f["ids"]["carol"]) as conn:
        assert (
            conn.execute(
                text("SELECT * FROM app.workspace_people(:w,NULL,100)"), {"w": f["w"]}
            ).all()
            == []
        )
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.memberships SET role='member' WHERE workspace_id=:w AND principal_id=:p"
            ),
            {"w": f["w"], "p": f["ids"]["bob"]},
        )
    assert f["clients"]["bob"].get(base).status_code == 403


def test_role_account_provisioning_persists_private_credentials_and_is_idempotent(
    access, tmp_path, monkeypatch
):
    f = access
    prefix = "role_" + uuid4().hex[:10]
    names = tuple(
        (prefix + suffix, role)
        for suffix, role in (
            ("_admin", "admin"),
            ("_viewer", "member"),
            ("_writer", "member"),
        )
    )
    monkeypatch.setattr(role_demo, "ACCOUNTS", names)
    path = tmp_path / "credentials.json"
    payload = None
    try:
        payload = role_demo.provision(f["owner"], f["w"], path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text()) == payload
        assert role_demo.provision(f["owner"], f["w"], path) == payload
        assert [item["role"] for item in payload["accounts"]] == [
            "admin",
            "member",
            "member",
        ]
        for collection in payload["collections"]:
            with transaction(f["runtime"], collection["member_id"]) as conn:
                permissions = collection_capabilities(conn, f["w"], collection["id"])
                assert permissions.permission == collection["permission"]
                assert permissions.can_manage is False
                assert permissions.can_ingest == (collection["permission"] == "ingest")
        with pytest.raises(ValueError, match="already in use"):
            role_demo.provision(f["owner"], f["w"], tmp_path / "other.json")
        assert not (tmp_path / "other.json").exists()
        with f["owner"].begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM app.source_grants WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": f["w"], "s": payload["collections"][0]["id"]},
            )
        with pytest.raises(ValueError, match="access changed"):
            role_demo.provision(f["owner"], f["w"], path)
    finally:
        if payload:
            with f["owner"].begin() as conn:
                for person in payload["accounts"]:
                    conn.execute(
                        text("DELETE FROM auth.principals WHERE id=:p"),
                        {"p": person["id"]},
                    )


def test_provisioning_file_error_rolls_back_accounts(access, tmp_path, monkeypatch):
    f = access
    prefix = "rollback_" + uuid4().hex[:8]
    names = tuple(
        (prefix + str(i), role) for i, role in enumerate(("admin", "member", "member"))
    )
    monkeypatch.setattr(role_demo, "ACCOUNTS", names)

    def fail_open(*args, **kwargs):
        raise PermissionError("fixture write denied")

    monkeypatch.setattr(role_demo.os, "open", fail_open)
    with pytest.raises(PermissionError):
        role_demo.provision(f["owner"], f["w"], tmp_path / "blocked.json")
    with f["owner"].connect() as conn:
        for username, _ in names:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM auth.principals WHERE username=:name"),
                    {"name": username},
                ).scalar_one()
                == 0
            )
