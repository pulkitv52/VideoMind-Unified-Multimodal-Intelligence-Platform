"""Real runtime-role signup, analytics, attribution and membership boundaries."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from test_access import access
from test_foundation import foundation, insert, pytestmark
from test_embedding_lifecycle import indexed, recipe, store, finish, build
from videomind.embeddings import initial
from videomind.embeddings.indexer import claim
from videomind.config import get_settings
from videomind.identity import self_service
from videomind.main import create_app
from videomind.infrastructure.database import transaction


@pytest.fixture
def service(access):
    f = access
    settings = get_settings().model_copy(update={"signup_workspace_id": str(f["w"])})
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth.signup_policies(workspace_id,enabled) VALUES(:w,true)"
            ),
            {"w": f["w"]},
        )
    names = []
    with ExitStack() as stack:
        clients = {
            name: stack.enter_context(TestClient(create_app(settings)))
            for name in ("alice", "bob", "carol", "anonymous")
        }
        for name in ("alice", "bob", "carol"):
            for cookie in f["clients"][name].cookies.jar:
                clients[name].cookies.set(cookie.name, cookie.value)

        def body():
            username = "signup_" + uuid4().hex[:16]
            names.append(username)
            return dict(
                username=username,
                password=uuid4().hex + uuid4().hex,
                accept_workspace_access=True,
            )

        try:
            yield f | {"clients": clients, "body": body}
        finally:
            with f["owner"].begin() as conn:
                for name in names:
                    # Only this fixture's new signup content/identities are removed.
                    conn.execute(
                        text(
                            "DELETE FROM app.sources WHERE workspace_id=:w AND created_by=(SELECT id FROM auth.principals WHERE username=:name)"
                        ),
                        {"w": f["w"], "name": name},
                    )
                    conn.execute(
                        text("DELETE FROM auth.principals WHERE username=:name"),
                        {"name": name},
                    )


def signup_body(f):
    body = f["body"]()
    return body | {"password_confirmation": body["password"]}


def test_signup_creates_only_member_own_collection_and_authenticated_session(service):
    f = service
    client = f["clients"]["anonymous"]
    assert client.get("/api/auth/signup-info").json() == {"enabled": True}
    body = signup_body(f)
    response = client.post("/api/auth/signup", json=body)
    assert response.status_code == 201
    assert response.json() == {"authenticated": True, "role": "member"}
    assert "httponly" in response.headers["set-cookie"].lower()
    assert body["password"] not in response.text
    me = client.get("/api/auth/me").json()
    spaces = client.get("/api/workspaces").json()
    assert len(spaces) == 1 and spaces[0]["role"] == "member"
    assert spaces[0]["can_create_collections"] and not spaces[0]["can_view_analytics"]
    collections = client.get(f"/api/workspaces/{f['w']}/sources").json()
    assert (
        len(collections) == 1
        and collections[0]["can_ingest"]
        and collections[0]["can_admin"]
    )
    assert client.get(f"/api/workspaces/{f['w']}/sources/{f['s']}").status_code == 404
    assert client.get(f"/api/workspaces/{f['w']}/analytics").status_code == 403
    assert client.get(f"/api/workspaces/{f['w']}/people").status_code == 403
    with f["owner"].connect() as conn:
        row = conn.execute(
            text("SELECT password_hash FROM auth.principals WHERE id=:p"),
            {"p": me["id"]},
        ).scalar_one()
        assert row.startswith("scrypt-v1$") and body["password"] not in row


@pytest.mark.parametrize(
    "patch",
    [
        {"role": "owner"},
        {"workspace_id": str(uuid4())},
        {"accept_workspace_access": False},
        {"password_confirmation": "mismatched-password"},
    ],
)
def test_signup_cannot_spoof_role_workspace_or_skip_confirmation(service, patch):
    f = service
    body = signup_body(f) | patch
    response = f["clients"]["anonymous"].post("/api/auth/signup", json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request"}
    assert body["password"] not in response.text


def test_registration_owner_control_capacity_and_case_insensitive_names(service):
    f = service
    client = f["clients"]["anonymous"]
    base = f"/api/workspaces/{f['w']}"
    for person in ("bob", "carol"):
        assert (
            f["clients"][person]
            .put(base + "/registration", json={"enabled": False})
            .status_code
            == 403
        )
    assert (
        f["clients"]["alice"]
        .put(base + "/registration", json={"enabled": False})
        .status_code
        == 200
    )
    assert client.post("/api/auth/signup", json=signup_body(f)).status_code == 403
    assert (
        f["clients"]["alice"]
        .put(base + "/registration", json={"enabled": True})
        .status_code
        == 200
    )
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE auth.signup_policies SET member_limit=3 WHERE workspace_id=:w"
            ),
            {"w": f["w"]},
        )
    assert client.post("/api/auth/signup", json=signup_body(f)).status_code == 409
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE auth.signup_policies SET member_limit=100 WHERE workspace_id=:w"
            ),
            {"w": f["w"]},
        )
    body = signup_body(f)
    assert client.post("/api/auth/signup", json=body).status_code == 201
    original = client.get("/api/auth/me").json()["id"]
    assert (
        client.post(
            "/api/auth/signup", json=body | {"username": body["username"].upper()}
        ).status_code
        == 409
    )
    assert client.get("/api/auth/me").json()["id"] == original


def test_signup_rolls_back_when_session_creation_fails(service, monkeypatch):
    f = service
    body = signup_body(f)

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic session failure")

    monkeypatch.setattr(self_service.secrets, "token_urlsafe", unavailable)
    response = f["clients"]["anonymous"].post("/api/auth/signup", json=body)
    assert response.status_code == 503 and body["password"] not in response.text
    with f["owner"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM auth.principals WHERE username=:name"),
                {"name": body["username"]},
            ).scalar_one()
            == 0
        )


def test_duplicate_signup_is_atomic_under_concurrent_delivery(service):
    f = service
    body = self_service.Signup(**signup_body(f))

    def submit():
        try:
            self_service.register(f["runtime"], f["w"], body)
            return 201
        except HTTPException as exc:
            return exc.status_code

    # Independent DB connections exercise the unique constraint and workspace lock.
    concurrent = create_engine(
        f["runtime"].url, pool_size=2, max_overflow=0, hide_parameters=True
    )
    original_runtime = f["runtime"]
    f["runtime"] = concurrent
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: submit(), range(2))) == [201, 409]
    finally:
        f["runtime"] = original_runtime
        concurrent.dispose()
    with f["owner"].connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.sources WHERE created_by=(SELECT id FROM auth.principals WHERE username=:name)"
                ),
                {"name": body.username},
            ).scalar_one()
            == 1
        )


def test_member_creates_writable_collection_without_granting_other_members_access(
    service,
):
    f = service
    member = f["clients"]["carol"]
    base = f"/api/workspaces/{f['w']}/sources"
    response = member.post(base, json={"name": "Own upload collection"})
    assert response.status_code == 201
    source = response.json()["id"]
    row = member.get(base + "/" + source).json()
    assert row["can_ingest"] and row["can_admin"]
    assert f["clients"]["bob"].get(base + "/" + source).status_code == 200
    assert (
        member.post(
            base,
            json={"name": "Forbidden host folder", "connector_kind": "local_folder"},
        ).status_code
        == 403
    )
    assert (
        member.post(
            base, json={"name": "Spoofed", "created_by": str(f["ids"]["alice"])}
        ).status_code
        == 422
    )
    assert (
        member.post(
            base + f"/{f['s']}/files?filename_value=denied.txt", content=b"Denied"
        ).status_code
        == 403
    )


def test_real_upload_attribution_analytics_scoping_and_filters(service):
    f = service
    uploader = f["clients"]["anonymous"]
    body = signup_body(f)
    assert uploader.post("/api/auth/signup", json=body).status_code == 201
    me = uploader.get("/api/auth/me").json()
    base = f"/api/workspaces/{f['w']}"
    source = uploader.get(base + "/sources").json()[0]["id"]
    upload = uploader.post(
        base + f"/sources/{source}/files?filename_value=activity-test.txt",
        content=b"Synthetic dashboard attribution test.",
    )
    assert upload.status_code == 202
    for person in ("alice", "bob"):
        response = f["clients"][person].get(
            base + "/analytics", params={"member": me["id"]}
        )
        assert response.status_code == 200
        activity = response.json()
        assert activity["summary"]["files"] == 1
        assert activity["summary"]["members"] == 4
        assert activity["summary"]["recent_members"] >= 1
        assert activity["uploads"][0]["uploader"] == body["username"]
        assert activity["uploads"][0]["title"] == "activity-test.txt"
        assert activity["uploads"][0]["status"] in {"preparing", "indexing", "ready"}
        assert activity["can_manage_roles"] == (person == "alice")
        assert (
            f["clients"][person]
            .get(base + "/analytics", params={"member": str(uuid4())})
            .json()["uploads"]
            == []
        )
    for client in (uploader, f["clients"]["carol"]):
        assert client.get(base + "/analytics").status_code == 403
    with transaction(f["runtime"], f["ids"]["carol"]) as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.upload_attribution WHERE workspace_id=:w"
                ),
                {"w": f["w"]},
            ).scalar_one()
            == 0
        )


def test_membership_changes_are_owner_scoped_versioned_and_audited(service):
    f = service
    base = f"/api/workspaces/{f['w']}"
    people = f["clients"]["alice"].get(base + "/people").json()["items"]
    member = next(person for person in people if person["role"] == "member")
    owner = next(person for person in people if person["role"] == "owner")
    target = base + "/people/" + member["principal_id"]
    change = {"version": member["version"], "role": "admin"}
    assert f["clients"]["bob"].post(target, json=change).status_code == 403
    assert f["clients"]["alice"].post(target, json=change).status_code == 200
    assert f["clients"]["alice"].post(target, json=change).status_code == 409
    assert (
        f["clients"]["alice"]
        .post(
            base + "/people/" + owner["principal_id"],
            json={"version": owner["version"], "role": "member"},
        )
        .status_code
        == 403
    )
    current = next(
        person
        for person in f["clients"]["alice"].get(base + "/people").json()["items"]
        if person["principal_id"] == member["principal_id"]
    )
    assert (
        f["clients"]["bob"]
        .post(target, json={"version": current["version"], "role": None})
        .status_code
        == 403
    )
    assert (
        f["clients"]["alice"]
        .post(target, json={"version": current["version"], "role": None})
        .status_code
        == 200
    )
    assert f["clients"]["carol"].get(base + "/capabilities").status_code == 404
    with transaction(f["runtime"], f["ids"]["alice"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.membership_audit WHERE workspace_id=:w"),
                {"w": f["w"]},
            ).scalar_one()
            == 2
        )


def test_initial_index_inventory_requires_prepared_content_and_live_owner(indexed):
    f = indexed
    with f["owner"].connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(
                text(
                    "INSERT INTO auth.signup_policies(workspace_id,enabled) VALUES(:w,true)"
                ),
                {"w": f["w"]},
            )
            rows = (
                conn.execute(
                    text(
                        "SELECT * FROM app.initial_index_work() WHERE workspace_id=:w"
                    ),
                    {"w": f["w"]},
                )
                .mappings()
                .all()
            )
            assert (
                len(rows) == 1
                and rows[0]["owner_id"] == f["actor"]
                and rows[0]["generation_id"] is None
            )
            conn.execute(
                text("UPDATE auth.principals SET disabled=true WHERE id=:p"),
                {"p": f["actor"]},
            )
            assert (
                conn.execute(
                    text(
                        "SELECT * FROM app.initial_index_work() WHERE workspace_id=:w"
                    ),
                    {"w": f["w"]},
                ).all()
                == []
            )
        finally:
            tx.rollback()


def test_signup_throttle_and_missing_configuration_fail_closed(service):
    f = service
    client = f["clients"]["anonymous"]
    with TestClient(
        create_app(get_settings().model_copy(update={"signup_workspace_id": ""}))
    ) as missing:
        assert missing.get("/api/auth/signup-info").json() == {"enabled": False}
        assert missing.post("/api/auth/signup", json=signup_body(f)).status_code == 403
    # Owner closing registration still consumes the bounded abuse allowance.
    f["clients"]["alice"].put(
        f"/api/workspaces/{f['w']}/registration", json={"enabled": False}
    )
    results = [
        client.post("/api/auth/signup", json=signup_body(f)).status_code
        for _ in range(11)
    ]
    assert results[:10] == [403] * 10 and results[-1] == 429


def test_initial_index_creation_completion_and_no_active_replacement(indexed):
    f = indexed

    class Profile:
        def profile(self):
            return recipe()

    # A closed registration policy keeps existing members' automatic indexing alive.
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth.signup_policies(workspace_id,enabled) VALUES(:w,false)"
            ),
            {"w": f["w"]},
        )
    initial.initialize(f["runtime"], Profile())
    with f["owner"].connect() as conn:
        gid = conn.execute(
            text(
                "SELECT initial_generation_id FROM auth.signup_policies WHERE workspace_id=:w"
            ),
            {"w": f["w"]},
        ).scalar_one()
    with transaction(f["runtime"], f["actor"]) as conn:
        job = claim(conn, f["w"], gid)
        profile = dict(
            conn.execute(
                text(
                    "SELECT g.profile_id,p.fingerprint FROM app.index_generations g JOIN app.embedding_profiles p ON (p.workspace_id,p.id)=(g.workspace_id,g.profile_id) WHERE g.workspace_id=:w AND g.id=:g"
                ),
                {"w": f["w"], "g": gid},
            )
            .mappings()
            .one()
        )
    # Incomplete coverage must remain unpublished, even on repeated delivery.
    initial.initialize(f["runtime"], Profile())
    with f["owner"].connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT active_generation_id FROM app.workspace_search_state WHERE workspace_id=:w"
                ),
                {"w": f["w"]},
            ).scalar_one_or_none()
            is None
        )
    store(f, job, profile)
    finish(f, job)
    initial.initialize(f["runtime"], Profile())
    initial.initialize(f["runtime"], Profile())
    with f["owner"].connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT active_generation_id FROM app.workspace_search_state WHERE workspace_id=:w"
                ),
                {"w": f["w"]},
            ).scalar_one()
            == gid
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM app.index_generations WHERE workspace_id=:w"
                ),
                {"w": f["w"]},
            ).scalar_one()
            == 1
        )


def test_file_index_retry_requires_write_and_only_requeues_failed_file(indexed):
    f = indexed
    gid, job, profile = build(f)
    with f["owner"].begin() as conn:
        insert(
            conn,
            "app.source_grants",
            workspace_id=f["w"],
            source_id=f["s"],
            principal_id=f["bob"],
            permission="read",
        )
        conn.execute(
            text(
                "UPDATE app.embedding_jobs SET status='failed',lease_token=NULL,error_code='synthetic_failure' WHERE id=:j"
            ),
            {"j": job["id"]},
        )
    base = f"/api/workspaces/{f['w']}/sources/{f['s']}/assets/{f['a']}/retry-index"
    client = f["clients"]["bob"]
    assert client.post(base).status_code == 403
    with f["owner"].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.source_grants SET permission='ingest' WHERE workspace_id=:w AND source_id=:s AND principal_id=:p"
            ),
            {"w": f["w"], "s": f["s"], "p": f["bob"]},
        )
    response = client.post(base)
    assert response.status_code == 200 and response.json() == {"queued": 1}
    assert client.post(base).json() == {"queued": 0}
    assert client.post(f"/api/workspaces/{f['w']}/indexes").status_code == 404


def test_analytics_pages_filters_and_unknown_history_are_honest(service):
    f = service
    with f["owner"].begin() as conn:
        for number in range(23):
            obj, asset, revision = uuid4(), uuid4(), uuid4()
            scope = dict(workspace_id=f["w"], source_id=f["s"])
            insert(
                conn,
                "app.objects",
                **scope,
                id=obj,
                bucket="videomind",
                object_key=str(obj),
                sha256="e" * 64,
                size_bytes=1,
                mime_type="text/plain",
                role="original",
            )
            insert(
                conn,
                "app.assets",
                **scope,
                id=asset,
                external_id=f"page-{number}",
                title=f"page-{number}.txt",
                modality="document",
                mime_type="text/plain",
            )
            insert(
                conn,
                "app.asset_revisions",
                **scope,
                id=revision,
                asset_id=asset,
                external_revision="v1",
                sha256="e" * 64,
                original_object_id=obj,
            )
            conn.execute(
                text(
                    "UPDATE app.assets SET latest_revision_id=:r WHERE workspace_id=:w AND id=:a"
                ),
                dict(w=f["w"], a=asset, r=revision),
            )
    client = f["clients"]["bob"]
    base = f"/api/workspaces/{f['w']}/analytics"
    first = client.get(base).json()
    assert first["summary"]["files"] == 23 and first["summary"]["preparing"] == 23
    assert len(first["uploads"]) == 20 and first["next_cursor"]
    assert all(row["uploader"] is None for row in first["uploads"])
    second = client.get(base, params={"after": first["next_cursor"]}).json()
    assert len(second["uploads"]) == 3 and second["next_cursor"] is None
    assert not {row["id"] for row in first["uploads"]} & {
        row["id"] for row in second["uploads"]
    }
    assert sum(row["uploads"] for row in first["trend"]) == 23
    assert client.get(base, params={"status": "ready"}).json()["uploads"] == []
    assert client.get(base, params={"modality": "video"}).json()["uploads"] == []
    assert client.get(base, params={"days": 91}).status_code == 422
