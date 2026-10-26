"""Operator-run persistent-demo RLS and live revocation drill; restores all grants."""

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

from sqlalchemy import create_engine, text

from videomind.infrastructure.database import transaction

TABLES = (
    "objects",
    "assets",
    "asset_revisions",
    "ingestion_jobs",
    "segments",
    "evidence_anchors",
    "citation_records",
    "embeddings",
    "searchable_text",
    "document_pages",
    "generation_assets",
    "embedding_jobs",
    "media_presentations",
    "media_artifacts",
    "segment_sets",
    "processing_runs",
    "stage_runs",
    "outbox",
    "segment_evidence",
    "segment_relations",
    "audit_events",
    "object_reservations",
    "source_grants",
    "upload_attribution",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.credentials.read_text())
    workspace = payload["workspace_id"]
    runtime = create_engine(os.environ["VM_DATABASE_URL"], hide_parameters=True)
    operator = create_engine(
        os.environ["VM_MIGRATION_DATABASE_URL"], hide_parameters=True
    )
    clients = []

    def request(client, path, method="GET", body=None):
        req = Request(
            "http://api:8000/api" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with client.open(req, timeout=20) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    try:
        with runtime.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
            ).one() == ("videomind_app", False, False)
        for index, account in enumerate(payload["accounts"]):
            client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            assert (
                request(
                    client,
                    "/auth/login",
                    "POST",
                    {"username": account["username"], "password": account["password"]},
                )[0]
                == 200
            )
            clients.append(client)
            with transaction(runtime, account["id"]) as conn:
                visible = set(
                    conn.execute(
                        text(
                            "SELECT id::text FROM app.sources WHERE workspace_id=:w AND NOT deleted"
                        ),
                        {"w": workspace},
                    ).scalars()
                )
                if index == 0:
                    assert {item["id"] for item in payload["collections"]} <= visible
                else:
                    expected = payload["collections"][index - 1]["id"]
                    assert visible == {expected}
                    for table in TABLES:
                        scopes = set(
                            conn.execute(
                                text(
                                    f"SELECT DISTINCT source_id::text FROM app.{table} WHERE workspace_id=:w"
                                ),
                                {"w": workspace},
                            ).scalars()
                        )
                        assert scopes <= {
                            expected
                        }, "Runtime-role content scope escaped"
                    assert (
                        conn.execute(
                            text(
                                "SELECT count(*) FROM app.embeddings WHERE workspace_id=:w"
                            ),
                            {"w": workspace},
                        ).scalar_one()
                        > 0
                    )
        # Same authenticated sessions must lose access immediately on the next request.
        viewer, contributor = clients[1:]
        collection = payload["collections"][0]
        params = {"w": workspace, "s": collection["id"], "p": collection["member_id"]}
        path = f"/workspaces/{workspace}/sources/{collection['id']}/assets"
        assert request(viewer, path)[0] == 200
        with operator.connect() as conn:
            original_grant = conn.execute(
                text(
                    "SELECT permission FROM app.source_grants WHERE workspace_id=:w AND source_id=:s AND principal_id=:p"
                ),
                params,
            ).scalar_one()
        try:
            with operator.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM app.source_grants WHERE workspace_id=:w AND source_id=:s AND principal_id=:p"
                    ),
                    params,
                )
            assert request(viewer, path)[0] == 404
            with transaction(runtime, collection["member_id"]) as conn:
                assert (
                    conn.execute(
                        text(
                            "SELECT count(*) FROM app.embeddings WHERE workspace_id=:w"
                        ),
                        {"w": workspace},
                    ).scalar_one()
                    == 0
                )
        finally:
            with operator.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO app.source_grants(workspace_id,source_id,principal_id,permission) VALUES(:w,:s,:p,:permission) ON CONFLICT(workspace_id,source_id,principal_id) DO UPDATE SET permission=EXCLUDED.permission"
                    ),
                    dict(params, permission=original_grant),
                )
        assert request(viewer, path)[0] == 200
        params = {"w": workspace, "p": payload["accounts"][2]["id"]}
        with operator.connect() as conn:
            original_membership = (
                conn.execute(
                    text(
                        "SELECT role,joined_at FROM app.memberships WHERE workspace_id=:w AND principal_id=:p"
                    ),
                    params,
                )
                .mappings()
                .one()
            )
        try:
            with operator.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM app.memberships WHERE workspace_id=:w AND principal_id=:p"
                    ),
                    params,
                )
            assert (
                request(contributor, f"/workspaces/{workspace}/capabilities")[0] == 404
            )
            with transaction(runtime, params["p"]) as conn:
                assert (
                    conn.execute(
                        text("SELECT count(*) FROM app.sources WHERE workspace_id=:w"),
                        {"w": workspace},
                    ).scalar_one()
                    == 0
                )
        finally:
            with operator.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO app.memberships(workspace_id,principal_id,role,joined_at) VALUES(:w,:p,:role,:joined_at) ON CONFLICT(workspace_id,principal_id) DO UPDATE SET role=EXCLUDED.role,joined_at=EXCLUDED.joined_at"
                    ),
                    dict(
                        params,
                        role=original_membership["role"],
                        joined_at=original_membership["joined_at"],
                    ),
                )
        assert request(contributor, f"/workspaces/{workspace}/capabilities")[0] == 200
        print(
            f"Passed actual runtime-role scope checks across {len(TABLES)} content tables, plus live grant/membership revocation and restoration."
        )
    finally:
        for client in clients:
            request(client, "/auth/logout", "POST", {})
        runtime.dispose()
        operator.dispose()


if __name__ == "__main__":
    main()
