"""Real runtime-role/PostgreSQL/HTTP checks; executed by the Compose verify job."""

import io
import os
import secrets
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from videomind.config import Settings
from videomind.identity.security import password_hash
from videomind.infrastructure.database import transaction
from videomind.infrastructure.services import object_client

pytestmark = pytest.mark.skipif(
    not os.getenv("VM_MIGRATION_DATABASE_URL"),
    reason="run through scripts/dev.py verify",
)

SOURCE_TABLES = (
    "sources",
    "document_pages",
    "media_presentations",
    "media_artifacts",
    "objects",
    "assets",
    "asset_revisions",
    "processing_runs",
    "stage_runs",
    "outbox",
    "segment_sets",
    "segments",
    "evidence_anchors",
    "segment_evidence",
    "segment_relations",
    "generation_assets",
    "embedding_jobs",
    "embeddings",
    "searchable_text",
    "citation_records",
    "audit_events",
)


def insert(conn, table, **values):
    # Identifiers are static test code; all data is bound separately.
    columns = ",".join(values)
    binds = ",".join(":" + key for key in values)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({binds})"), values)


@pytest.fixture(scope="module")
def foundation():
    owner = create_engine(os.environ["VM_MIGRATION_DATABASE_URL"], hide_parameters=True)
    runtime = create_engine(
        os.environ["VM_DATABASE_URL"], pool_size=1, max_overflow=0, hide_parameters=True
    )
    ids = {
        name: uuid4()
        for name in (
            "alice",
            "bob",
            "carol",
            "workspace",
            "other_workspace",
            "private",
            "shared",
            "foreign",
        )
    }
    clients = {}
    names = {
        name: "verify_" + uuid4().hex[:12] + "_" + name
        for name in ("alice", "bob", "carol")
    }
    password = secrets.token_urlsafe(24)
    hashed = password_hash(password)
    with owner.begin() as conn:
        for name in names:
            insert(
                conn,
                "auth.principals",
                id=ids[name],
                username=names[name],
                password_hash=hashed,
            )
        for key in ("workspace", "other_workspace"):
            insert(conn, "app.workspaces", id=ids[key], name="Verification " + key)
        for user, w, role in (
            ("alice", "workspace", "owner"),
            ("bob", "workspace", "member"),
            ("carol", "other_workspace", "owner"),
        ):
            insert(
                conn,
                "app.memberships",
                workspace_id=ids[w],
                principal_id=ids[user],
                role=role,
            )
        for source, w in (
            ("private", "workspace"),
            ("shared", "workspace"),
            ("foreign", "other_workspace"),
        ):
            insert(
                conn,
                "app.sources",
                workspace_id=ids[w],
                id=ids[source],
                name="Verification " + source,
                connector_kind="upload",
            )
        insert(
            conn,
            "app.source_grants",
            workspace_id=ids["workspace"],
            source_id=ids["shared"],
            principal_id=ids["bob"],
            permission="read",
        )
        profiles = {}
        for source, w in (
            ("private", "workspace"),
            ("shared", "workspace"),
            ("foreign", "other_workspace"),
        ):
            scope = {"workspace_id": ids[w], "source_id": ids[source]}
            if w not in profiles:
                p, g = uuid4(), uuid4()
                insert(
                    conn,
                    "app.embedding_profiles",
                    workspace_id=ids[w],
                    id=p,
                    fingerprint="a" * 64,
                    model_id="google/embeddinggemma-2",
                    model_revision="b" * 40,
                    configuration="{}",
                    dimension=768,
                )
                insert(
                    conn,
                    "app.index_generations",
                    workspace_id=ids[w],
                    id=g,
                    profile_id=p,
                )
                insert(
                    conn,
                    "app.workspace_search_state",
                    workspace_id=ids[w],
                    active_generation_id=g,
                )
                profiles[w] = (p, g)
            p, g = profiles[w]
            obj, asset, rev, run, stage, segments, seg, neighbor, anchor = tuple(
                uuid4() for _ in range(9)
            )
            insert(
                conn,
                "app.objects",
                **scope,
                id=obj,
                bucket="videomind",
                object_key=f"{ids[w]}/{ids[source]}/{obj}",
                sha256="c" * 64,
                size_bytes=20,
                mime_type="text/plain",
                role="original",
            )
            insert(
                conn,
                "app.assets",
                **scope,
                id=asset,
                external_id=str(asset),
                title="Synthetic evidence",
                modality="document",
                mime_type="text/plain",
            )
            insert(
                conn,
                "app.asset_revisions",
                **scope,
                id=rev,
                asset_id=asset,
                external_revision="v1",
                sha256="c" * 64,
                original_object_id=obj,
            )
            insert(
                conn,
                "app.processing_runs",
                **scope,
                id=run,
                revision_id=rev,
                profile_hash="d" * 64,
            )
            insert(
                conn,
                "app.stage_runs",
                **scope,
                id=stage,
                processing_run_id=run,
                stage="fixture",
                configuration_hash="e" * 64,
            )
            insert(
                conn, "app.outbox", **scope, processing_run_id=run, event_type="fixture"
            )
            insert(
                conn,
                "app.segment_sets",
                **scope,
                id=segments,
                revision_id=rev,
                processing_run_id=run,
                segmenter_profile="fixture-v1",
            )
            insert(
                conn,
                "app.document_pages",
                **scope,
                segment_set_id=segments,
                revision_id=rev,
                page=1,
                text_object_id=obj,
                manifest="{}",
            )
            insert(
                conn,
                "app.media_presentations",
                **scope,
                segment_set_id=segments,
                revision_id=rev,
                playback_object_id=obj,
                mapping_object_id=obj,
                manifest="{}",
            )
            insert(
                conn,
                "app.media_artifacts",
                **scope,
                segment_set_id=segments,
                object_id=obj,
            )
            for ordinal, segment in enumerate((seg, neighbor)):
                insert(
                    conn,
                    "app.segments",
                    **scope,
                    id=segment,
                    segment_set_id=segments,
                    revision_id=rev,
                    representation="text",
                    ordinal=ordinal,
                    text_content="Synthetic evidence",
                    producer="verification",
                )
            insert(
                conn,
                "app.evidence_anchors",
                **scope,
                id=anchor,
                revision_id=rev,
                original_object_id=obj,
                locator_kind="page",
                page=1,
            )
            insert(
                conn,
                "app.segment_evidence",
                **scope,
                segment_id=seg,
                anchor_id=anchor,
                revision_id=rev,
                relation="extracted_from",
                producer="verification",
            )
            insert(
                conn,
                "app.segment_relations",
                **scope,
                from_id=seg,
                to_id=neighbor,
                relation="overlaps",
                producer="verification",
            )
            insert(
                conn,
                "app.generation_assets",
                **scope,
                generation_id=g,
                asset_id=asset,
                revision_id=rev,
                segment_set_id=segments,
            )
            insert(
                conn,
                "app.embedding_jobs",
                **scope,
                generation_id=g,
                asset_id=asset,
                revision_id=rev,
                segment_set_id=segments,
            )
            insert(
                conn,
                "app.embeddings",
                **scope,
                segment_id=seg,
                profile_id=p,
                input_hash="f" * 64,
                embedding="[1," + ",".join(["0"] * 767) + "]",
            )
            conn.execute(
                text(
                    "INSERT INTO app.searchable_text(workspace_id,source_id,segment_id,text_content,lexemes) VALUES (:w,:s,:seg,'Synthetic evidence',to_tsvector('simple','Synthetic evidence'))"
                ),
                {"w": ids[w], "s": ids[source], "seg": seg},
            )
            insert(
                conn, "app.citation_records", **scope, segment_id=seg, anchor_id=anchor
            )
            insert(
                conn,
                "app.audit_events",
                **scope,
                actor_id=ids["alice" if w == "workspace" else "carol"],
                action="fixture",
                outcome="success",
                trace_id=uuid4(),
            )
        version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        ).scalar_one()
        assert version
    for user in names:
        client = httpx.Client(base_url="http://api:8000", timeout=10)
        assert (
            client.post(
                "/api/auth/login", json={"username": names[user], "password": password}
            ).status_code
            == 200
        )
        clients[user] = client
    yield ids, owner, runtime, clients, names, password
    for client in clients.values():
        client.close()
    runtime.dispose()
    # A live worker can finish a disposable job while its workspace cascades.
    # Retry only PostgreSQL's deadlock victim, using a fresh transaction.
    for attempt in range(3):
        try:
            with owner.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM app.object_reservations WHERE workspace_id IN (:one,:two)"
                    ),
                    {"one": ids["workspace"], "two": ids["other_workspace"]},
                )
                conn.execute(
                    text("DELETE FROM app.workspaces WHERE id IN (:one,:two)"),
                    {"one": ids["workspace"], "two": ids["other_workspace"]},
                )
                for user in names:
                    conn.execute(
                        text("DELETE FROM auth.principals WHERE id=:id"),
                        {"id": ids[user]},
                    )
            break
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "40P01" or attempt == 2:
                raise
            time.sleep(0.25)
    owner.dispose()


def test_runtime_role_is_restricted_and_no_actor_sees_no_content(foundation):
    ids, _, engine, *_ = foundation
    with transaction(engine) as conn:
        role = conn.execute(
            text(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        assert role == (False, False)
        assert conn.execute(text("SELECT count(*) FROM app.sources")).scalar_one() == 0
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='app' AND tableowner=current_user"
                )
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("table", SOURCE_TABLES)
def test_every_content_table_enforces_source_and_workspace_isolation(foundation, table):
    ids, _, engine, *_ = foundation
    column = "id" if table == "sources" else "source_id"
    for user, expected in (
        ("bob", {ids["shared"]}),
        ("alice", {ids["private"], ids["shared"]}),
        ("carol", {ids["foreign"]}),
    ):
        with transaction(engine, ids[user]) as conn:
            assert (
                set(conn.execute(text(f"SELECT {column} FROM app.{table}")).scalars())
                == expected
            )
    with engine.begin() as conn:
        # The single-connection pool must not retain the previous transaction's actor.
        assert conn.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0


def test_http_identity_is_server_derived_and_hidden_sources_are_404(foundation):
    ids, _, _, clients, *_ = foundation
    bob = clients["bob"]
    assert bob.get("/api/auth/me").json()["id"] == str(ids["bob"])
    assert [row["id"] for row in bob.get("/api/workspaces").json()] == [
        str(ids["workspace"])
    ]
    assert [
        row["id"]
        for row in bob.get(f"/api/workspaces/{ids['workspace']}/sources").json()
    ] == [str(ids["shared"])]
    for source, w in (("private", "workspace"), ("foreign", "other_workspace")):
        response = bob.get(
            f"/api/workspaces/{ids[w]}/sources/{ids[source]}",
            headers={"X-Actor-ID": str(ids["alice"])},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Source unavailable"}
        assert response.headers["X-Request-ID"]


def test_read_grant_cannot_write_or_cross_scope(foundation):
    ids, _, engine, *_ = foundation
    with pytest.raises(DBAPIError):
        with transaction(engine, ids["bob"]) as conn:
            insert(
                conn,
                "app.assets",
                workspace_id=ids["workspace"],
                source_id=ids["shared"],
                external_id=str(uuid4()),
                title="Denied",
                modality="document",
                mime_type="text/plain",
            )
    with pytest.raises(DBAPIError):
        with transaction(engine, ids["alice"]) as conn:
            insert(
                conn,
                "app.assets",
                workspace_id=ids["workspace"],
                source_id=ids["foreign"],
                external_id=str(uuid4()),
                title="Wrong scope",
                modality="document",
                mime_type="text/plain",
            )
    with pytest.raises(DBAPIError):
        with transaction(engine, ids["alice"]) as conn:
            conn.execute(
                text(
                    "UPDATE app.assets SET source_id=:new WHERE workspace_id=:w AND source_id=:old"
                ),
                {"new": ids["private"], "w": ids["workspace"], "old": ids["shared"]},
            )


def test_revoking_grant_applies_to_existing_session_and_membership_is_required(
    foundation,
):
    ids, owner, _, clients, *_ = foundation
    with owner.begin() as conn:
        conn.execute(
            text("DELETE FROM app.source_grants WHERE principal_id=:p"),
            {"p": ids["bob"]},
        )
    try:
        assert (
            clients["bob"].get(f"/api/workspaces/{ids['workspace']}/sources").json()
            == []
        )
    finally:
        with owner.begin() as conn:
            insert(
                conn,
                "app.source_grants",
                workspace_id=ids["workspace"],
                source_id=ids["shared"],
                principal_id=ids["bob"],
                permission="read",
            )
    with owner.begin() as conn:
        conn.execute(
            text("DELETE FROM app.memberships WHERE principal_id=:p"), {"p": ids["bob"]}
        )
    try:
        assert clients["bob"].get("/api/workspaces").json() == []
        assert (
            clients["bob"]
            .get(f"/api/workspaces/{ids['workspace']}/sources")
            .status_code
            == 404
        )
    finally:
        with owner.begin() as conn:
            insert(
                conn,
                "app.memberships",
                workspace_id=ids["workspace"],
                principal_id=ids["bob"],
                role="member",
            )


def test_logout_revokes_session_and_anonymous_content_is_denied(foundation):
    _, _, _, _, names, password = foundation
    with httpx.Client(base_url="http://api:8000", timeout=10) as client:
        assert client.get("/api/workspaces").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                json={"username": names["alice"], "password": password},
            ).status_code
            == 200
        )
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/workspaces").status_code == 401


def test_private_object_storage_is_usable_but_not_anonymous(foundation):
    settings = Settings()
    client = object_client(settings)
    key = ".verification/" + uuid4().hex
    body = b"synthetic verification object"
    client.put_object(settings.minio_bucket, key, io.BytesIO(body), len(body))
    try:
        response = client.get_object(settings.minio_bucket, key)
        try:
            assert response.read() == body
        finally:
            response.close()
            response.release_conn()
        assert (
            httpx.get(f"http://minio:9000/{settings.minio_bucket}/{key}").status_code
            == 403
        )
    finally:
        client.remove_object(settings.minio_bucket, key)


def test_workspace_metadata_and_all_app_tables_are_protected(foundation):
    ids, _, engine, *_ = foundation
    with transaction(engine, ids["bob"]) as conn:
        rows = conn.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='app' AND relkind='r'"
            )
        ).all()
        assert len(rows) == 32
        assert all(enabled and forced for enabled, forced in rows)
        for table in (
            "workspaces",
            "memberships",
            "source_grants",
            "embedding_profiles",
            "index_generations",
            "workspace_search_state",
        ):
            column = "id" if table == "workspaces" else "workspace_id"
            assert set(
                conn.execute(text(f"SELECT {column} FROM app.{table}")).scalars()
            ) == {ids["workspace"]}


def test_evidence_requires_a_valid_locator_and_immutable_rows_stay_immutable(
    foundation,
):
    ids, _, engine, *_ = foundation
    with transaction(engine, ids["alice"]) as conn:
        row = conn.execute(
            text(
                "SELECT revision_id,original_object_id FROM app.evidence_anchors WHERE source_id=:s"
            ),
            {"s": ids["private"]},
        ).one()
    with pytest.raises(DBAPIError):
        with transaction(engine, ids["alice"]) as conn:
            insert(
                conn,
                "app.evidence_anchors",
                workspace_id=ids["workspace"],
                source_id=ids["private"],
                revision_id=row.revision_id,
                original_object_id=row.original_object_id,
                locator_kind="page",
            )
    with pytest.raises(DBAPIError):
        with transaction(engine, ids["alice"]) as conn:
            conn.execute(
                text("UPDATE app.evidence_anchors SET page=2 WHERE source_id=:s"),
                {"s": ids["private"]},
            )


def test_migrations_upgrade_an_empty_database():
    import subprocess
    from sqlalchemy.engine import make_url

    owner_url = make_url(os.environ["VM_MIGRATION_DATABASE_URL"])
    scratch = "videomind_verify_" + uuid4().hex
    admin = create_engine(owner_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    fresh_url = owner_url.set(database=scratch)
    with admin.connect() as conn:
        # Name is generated internally from a UUID, never from an imported identifier.
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    try:
        env = dict(
            os.environ,
            VM_MIGRATION_DATABASE_URL=fresh_url.render_as_string(hide_password=False),
        )
        result = subprocess.run(
            ["alembic", "upgrade", "head"], env=env, capture_output=True, text=True
        )
        assert (
            result.returncode == 0
        ), "Fresh database migration failed; inspect migration diagnostics locally"
        fresh = create_engine(fresh_url, hide_parameters=True)
        try:
            with fresh.connect() as conn:
                assert (
                    conn.execute(
                        text("SELECT version_num FROM public.alembic_version")
                    ).scalar_one()
                    == "0022_self_service"
                )
                assert (
                    conn.execute(
                        text("SELECT count(*) FROM pg_tables WHERE schemaname='app'")
                    ).scalar_one()
                    == 32
                )
        finally:
            fresh.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{scratch}" WITH (FORCE)'))
        admin.dispose()


def wait_intake(client, base, job_id):
    import time

    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        jobs = client.get(base + "/jobs").json()
        job = next(j for j in jobs if j["id"] == job_id)
        if job["status"] in {"stored", "failed", "cancelled"}:
            return job
        time.sleep(0.5)
    pytest.fail("Intake did not reach a terminal state")


def test_upload_ui_api_preserves_originals_and_revisions_without_duplicates(foundation):
    ids, owner, engine, clients, *_ = foundation
    alice, bob = clients["alice"], clients["bob"]
    response = alice.post(
        f"/api/workspaces/{ids['workspace']}/sources",
        json={"name": "Upload verification", "connector_kind": "upload"},
    )
    assert response.status_code == 201
    source = response.json()["id"]
    base = f"/api/workspaces/{ids['workspace']}/sources/{source}"
    assert (
        bob.post(
            f"/api/workspaces/{ids['workspace']}/sources",
            json={"name": "Denied", "connector_kind": "local_folder"},
        ).status_code
        == 403
    )
    first = alice.post(
        base + "/files",
        params={"filename_value": "notes.txt"},
        content=b"first immutable revision",
    )
    assert first.status_code == 202
    original = first.json()
    assert wait_intake(alice, base, original["job_id"])["status"] == "stored"
    duplicate = alice.post(
        base + "/files",
        params={"filename_value": "notes.txt"},
        content=b"first immutable revision",
    ).json()
    assert (
        duplicate["unchanged"]
        and duplicate["revision_id"] == original["revision_id"]
        and duplicate["job_id"] == original["job_id"]
    )
    second = alice.post(
        base + "/files",
        params={"filename_value": "notes.txt"},
        content=b"second immutable revision",
    ).json()
    assert (
        second["asset_id"] == original["asset_id"]
        and second["revision_id"] != original["revision_id"]
    )
    assert wait_intake(alice, base, second["job_id"])["status"] == "stored"
    assets = alice.get(base + "/assets").json()
    assert len(assets) == 1 and assets[0]["status"] == "stored"
    download = alice.get(base + f"/assets/{original['asset_id']}/original")
    assert download.content == b"second immutable revision"
    assert "attachment;" in download.headers["content-disposition"]
    for path in ("/assets", "/jobs", f"/assets/{original['asset_id']}/original"):
        assert bob.get(base + path).status_code == 404
    assert (
        bob.post(
            base + "/files", params={"filename_value": "x.txt"}, content=b"denied"
        ).status_code
        == 404
    )
    with transaction(engine, ids["alice"]) as conn:
        revisions = (
            conn.execute(
                text(
                    "SELECT sha256 FROM app.asset_revisions WHERE workspace_id=:w AND source_id=:s"
                ),
                {"w": ids["workspace"], "s": source},
            )
            .scalars()
            .all()
        )
        assert len(revisions) == 2 and len(set(revisions)) == 2
    with transaction(engine, ids["bob"]) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.ingestion_jobs WHERE source_id=:s"),
                {"s": source},
            ).scalar_one()
            == 0
        )


def test_upload_rejections_async_failure_retry_and_source_tombstone(foundation):
    ids, _, engine, clients, *_ = foundation
    alice = clients["alice"]
    source = alice.post(
        f"/api/workspaces/{ids['workspace']}/sources",
        json={"name": "Failure verification"},
    ).json()["id"]
    base = f"/api/workspaces/{ids['workspace']}/sources/{source}"
    for name, data in (
        ("../escape.txt", b"text"),
        ("fake.png", b"not an image"),
        ("tool.exe", b"MZ..."),
        ("empty.txt", b""),
    ):
        assert (
            alice.post(
                base + "/files", params={"filename_value": name}, content=data
            ).status_code
            == 422
        )
    bad = alice.post(
        base + "/files",
        params={"filename_value": "broken.pdf"},
        content=b"%PDF-1.7\nbroken payload",
    ).json()
    failed = wait_intake(alice, base, bad["job_id"])
    assert (
        failed["status"] == "failed"
        and failed["error_code"] == "STRUCTURAL_VALIDATION_FAILED"
    )
    assert alice.post(base + f"/jobs/{bad['job_id']}/retry").status_code == 202
    assert wait_intake(alice, base, bad["job_id"])["status"] == "failed"
    assert alice.delete(base).status_code == 204
    assert alice.get(base + "/assets").status_code == 404
    assert alice.get(base + f"/assets/{bad['asset_id']}/original").status_code == 404
    with engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT app.intake_claim(:w,:s,:j)"),
                {"w": ids["workspace"], "s": source, "j": bad["job_id"]},
            ).scalar_one()
            is None
        )


def test_source_admin_can_cancel_another_ingesters_jobs(foundation):
    ids, owner, _, clients, *_ = foundation
    alice, bob = clients["alice"], clients["bob"]
    source = alice.post(
        f"/api/workspaces/{ids['workspace']}/sources",
        json={"name": "Shared intake cancellation"},
    ).json()["id"]
    with owner.begin() as conn:
        insert(
            conn,
            "app.source_grants",
            workspace_id=ids["workspace"],
            source_id=source,
            principal_id=ids["bob"],
            permission="ingest",
        )
    base = f"/api/workspaces/{ids['workspace']}/sources/{source}"
    result = bob.post(
        base + "/files",
        params={"filename_value": "shared.txt"},
        content=b"shared intake",
    )
    assert result.status_code == 202
    assert bob.delete(base).status_code == 403
    assert alice.delete(base).status_code == 204
    assert bob.get(base + "/assets").status_code == 404
