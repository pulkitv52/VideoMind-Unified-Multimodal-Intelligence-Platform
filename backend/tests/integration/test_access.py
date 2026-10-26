"""Access-policy and ownership invariants using actual restricted-role transactions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import os
import subprocess
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from test_foundation import foundation, insert, pytestmark
from videomind.identity.access import require_workspace_owner
from videomind.infrastructure.database import transaction
from videomind.main import create_app


@pytest.fixture
def access(foundation):
    ids, owner, runtime, clients, *_ = foundation
    workspace, source, hidden = uuid4(), uuid4(), uuid4()
    with owner.begin() as conn:
        insert(conn, "app.workspaces", id=workspace, name="Access fixture")
        for person, role in (("alice", "owner"), ("bob", "admin"), ("carol", "member")):
            insert(
                conn,
                "app.memberships",
                workspace_id=workspace,
                principal_id=ids[person],
                role=role,
            )
        for source_id in (source, hidden):
            insert(
                conn,
                "app.sources",
                workspace_id=workspace,
                id=source_id,
                name="Access fixture",
                connector_kind="upload",
            )
        insert(
            conn,
            "app.source_grants",
            workspace_id=workspace,
            source_id=source,
            principal_id=ids["carol"],
            permission="read",
        )
    try:
        with ExitStack() as stack:
            local_clients = {}
            for person, client in clients.items():
                local = stack.enter_context(TestClient(create_app()))
                for cookie in client.cookies.jar:
                    local.cookies.set(cookie.name, cookie.value)
                local_clients[person] = local
            yield dict(
                ids=ids,
                owner=owner,
                runtime=runtime,
                clients=local_clients,
                w=workspace,
                s=source,
                hidden=hidden,
            )
    finally:
        with owner.begin() as conn:
            conn.execute(
                text("DELETE FROM app.workspaces WHERE id=:w"), {"w": workspace}
            )


def test_workspace_capability_and_owner_guard_matrix(access):
    f = access
    for person, role in (("alice", "owner"), ("bob", "admin"), ("carol", "member")):
        response = f["clients"][person].get(f"/api/workspaces/{f['w']}/capabilities")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == dict(
            workspace_id=str(f["w"]),
            role=role,
            can_create_collections=True,
            can_import_folders=role != "member",
            can_manage_index=role != "member",
            can_view_storage=role != "member",
            can_view_analytics=role != "member",
            can_manage_members=role != "member",
            can_manage_roles=role == "owner",
            can_transfer_ownership=role == "owner",
        )
        with transaction(f["runtime"], f["ids"][person]) as conn:
            if person == "alice":
                require_workspace_owner(conn, f["w"])
            else:
                with pytest.raises(HTTPException) as exc:
                    require_workspace_owner(conn, f["w"])
                assert exc.value.status_code == 403


def test_capabilities_deny_foreign_workspace_anonymous_and_spoofed_actor(
    access, foundation
):
    f = access
    ids, *_ = foundation
    client = f["clients"]["alice"]
    for workspace in (ids["other_workspace"], uuid4()):
        result = client.get(
            f"/api/workspaces/{workspace}/capabilities",
            headers={"X-Actor-ID": str(ids["carol"])},
        )
        assert result.status_code == 404
        assert result.json() == {"detail": "Workspace unavailable"}
    client.cookies.clear()
    assert client.get(f"/api/workspaces/{f['w']}/capabilities").status_code == 401


@pytest.mark.parametrize("permission", ["read", "ingest", "admin"])
def test_collection_grants_do_not_escalate_workspace_role(access, permission):
    f = access
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.source_grants SET permission=:permission WHERE workspace_id=:w"
            ),
            dict(w=f["w"], permission=permission),
        )
    base = f"/api/workspaces/{f['w']}/sources"
    member = f["clients"]["carol"]
    value = member.get(f"{base}/{f['s']}/capabilities")
    assert value.status_code == 200
    assert value.json() == dict(
        workspace_id=str(f["w"]),
        source_id=str(f["s"]),
        permission=permission,
        can_read=True,
        can_ingest=permission != "read",
        can_manage=permission == "admin",
    )
    for source in (f["hidden"], uuid4()):
        result = member.get(f"{base}/{source}/capabilities")
        assert result.status_code == 404
        assert result.json() == {"detail": "Source unavailable"}
    for person in ("alice", "bob"):
        result = f["clients"][person].get(f"{base}/{f['hidden']}/capabilities")
        assert result.json()["permission"] == "workspace_admin"
        assert result.json()["can_manage"] is True
    assert (
        member.post(
            base, json={"name": "Must not create", "connector_kind": "local_folder"}
        ).status_code
        == 403
    )


def test_capabilities_recheck_role_grants_membership_and_deleted_source(access):
    f = access
    member = f["clients"]["carol"]
    path = f"/api/workspaces/{f['w']}/sources/{f['s']}/capabilities"
    assert member.get(path).status_code == 200
    with f["owner"].begin() as conn:
        conn.execute(
            text("DELETE FROM app.source_grants WHERE workspace_id=:w"), {"w": f["w"]}
        )
        conn.execute(
            text(
                "UPDATE app.memberships SET role='member' WHERE workspace_id=:w AND principal_id=:p"
            ),
            dict(w=f["w"], p=f["ids"]["bob"]),
        )
    assert member.get(path).status_code == 404
    admin = f["clients"]["bob"]
    assert (
        admin.get(f"/api/workspaces/{f['w']}/capabilities").json()["can_manage_index"]
        is False
    )
    assert admin.get(path).status_code == 404
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "DELETE FROM app.memberships WHERE workspace_id=:w AND principal_id=:p"
            ),
            dict(w=f["w"], p=f["ids"]["carol"]),
        )
        conn.execute(
            text("UPDATE app.sources SET deleted=true WHERE workspace_id=:w AND id=:s"),
            dict(w=f["w"], s=f["s"]),
        )
    assert member.get(f"/api/workspaces/{f['w']}/capabilities").status_code == 404
    assert f["clients"]["alice"].get(path).status_code == 404


def test_runtime_cannot_write_memberships_or_call_internal_trigger_functions(access):
    f = access
    for statement in (
        "UPDATE app.memberships SET role='owner' WHERE workspace_id=:w AND principal_id=:p",
        "DELETE FROM app.memberships WHERE workspace_id=:w",
        "SELECT app.check_workspace_owner()",
        "SELECT app.lock_membership_workspace()",
    ):
        with pytest.raises(DBAPIError) as exc:
            with transaction(f["runtime"], f["ids"]["bob"]) as conn:
                conn.execute(text(statement), dict(w=f["w"], p=f["ids"]["bob"]))
        assert exc.value.orig.sqlstate == "42501"


def test_ownership_constraint_rejects_ownerless_and_duplicate_owners(access):
    f = access
    for statement in (
        "DELETE FROM app.memberships WHERE workspace_id=:w AND role='owner'",
        "UPDATE app.memberships SET role='member' WHERE workspace_id=:w AND role='owner'",
        "UPDATE app.memberships SET role='owner' WHERE workspace_id=:w AND principal_id=:p",
    ):
        with pytest.raises(DBAPIError) as exc:
            with f["owner"].begin() as conn:
                conn.execute(text(statement), dict(w=f["w"], p=f["ids"]["bob"]))
        assert exc.value.orig.sqlstate in {"23505", "23514"}
    with pytest.raises(DBAPIError) as exc:
        with f["owner"].begin() as conn:
            insert(conn, "app.workspaces", id=uuid4(), name="Ownerless fixture")
    assert exc.value.orig.sqlstate == "23514"
    # A future ownership service can demote/promote atomically; neither commit
    # nor a concurrent writer may observe an ownerless committed workspace.
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.memberships SET role='admin' WHERE workspace_id=:w AND role='owner'"
            ),
            {"w": f["w"]},
        )
        conn.execute(
            text(
                "UPDATE app.memberships SET role='owner' WHERE workspace_id=:w AND principal_id=:p"
            ),
            dict(w=f["w"], p=f["ids"]["bob"]),
        )
    with transaction(f["runtime"], f["ids"]["bob"]) as conn:
        require_workspace_owner(conn, f["w"])


def test_membership_writes_serialize_on_workspace(access):
    f = access

    def concurrent_write():
        try:
            with f["owner"].begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout='200ms'"))
                conn.execute(
                    text(
                        "UPDATE app.memberships SET role='admin' WHERE workspace_id=:w AND principal_id=:p"
                    ),
                    dict(w=f["w"], p=f["ids"]["carol"]),
                )
        except DBAPIError as exc:
            return exc.orig.sqlstate
        return "unexpected_success"

    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.memberships SET role=role WHERE workspace_id=:w AND principal_id=:p"
            ),
            dict(w=f["w"], p=f["ids"]["bob"]),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(concurrent_write).result(timeout=5) == "55P03"


@pytest.mark.parametrize("owner_count", [0, 2])
def test_upgrade_rejects_ambiguous_ownership_without_altering_memberships(owner_count):
    owner_url = make_url(os.environ["VM_MIGRATION_DATABASE_URL"])
    scratch = "videomind_access_" + uuid4().hex
    admin = create_engine(owner_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    fresh_url = owner_url.set(database=scratch)
    fresh = create_engine(fresh_url, hide_parameters=True)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    try:
        env = dict(
            os.environ,
            VM_MIGRATION_DATABASE_URL=fresh_url.render_as_string(hide_password=False),
        )
        result = subprocess.run(
            ["alembic", "upgrade", "0019_recovery_journal"],
            env=env,
            capture_output=True,
            timeout=40,
        )
        assert result.returncode == 0, "Access migration fixture setup failed"
        w = uuid4()
        with fresh.begin() as conn:
            insert(conn, "app.workspaces", id=w, name="Migration fixture")
            for _ in range(owner_count):
                p = uuid4()
                insert(
                    conn,
                    "auth.principals",
                    id=p,
                    username="migration_" + p.hex,
                    password_hash="fixture",
                )
                insert(
                    conn,
                    "app.memberships",
                    workspace_id=w,
                    principal_id=p,
                    role="owner",
                )
        result = subprocess.run(
            ["alembic", "upgrade", "head"], env=env, capture_output=True, timeout=40
        )
        assert result.returncode != 0
        assert b"ownership needs operator reconciliation" in result.stderr
        with fresh.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0019_recovery_journal"
            )
            assert (
                conn.execute(text("SELECT count(*) FROM app.memberships")).scalar_one()
                == owner_count
            )
    finally:
        fresh.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{scratch}" WITH (FORCE)'))
        admin.dispose()
