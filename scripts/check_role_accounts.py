"""Exercise provisioned local role accounts; secrets stay in ignored .local files."""

import argparse
import http.cookiejar
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self):
        self.http = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, method="GET", body=None, raw=None):
        data = json.dumps(body).encode() if body is not None else raw
        request = Request(
            "http://127.0.0.1:8000/api" + path,
            method=method,
            data=data,
            headers={
                "Content-Type": (
                    "application/octet-stream"
                    if raw is not None
                    else "application/json"
                )
            },
        )
        try:
            with self.http.open(request, timeout=30) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def json(self, path, **kwargs):
        status, body = self.request(path, **kwargs)
        if status >= 400:
            raise AssertionError(
                f"Expected successful local request; received {status}"
            )
        return json.loads(body) if body else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Add the two synthetic fixture files if absent",
    )
    args = parser.parse_args()
    payload = json.loads((ROOT / ".local/role-test-accounts.json").read_text())
    credentials = [
        json.loads((ROOT / ".local/owner.json").read_text()),
        *payload["accounts"],
    ]
    clients = {}
    checks = []
    base = "/workspaces/" + payload["workspace_id"]

    def expect(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    try:
        for account in credentials:
            client = Client()
            client.json(
                "/auth/login",
                method="POST",
                body={"username": account["username"], "password": account["password"]},
            )
            clients[account["username"]] = client
        owner, admin, viewer, contributor = [
            clients[account["username"]] for account in credentials
        ]
        sources = payload["collections"]
        for index, collection in enumerate(sources):
            source_base = base + "/sources/" + collection["id"]
            files = admin.json(source_base + "/assets")
            if not files and args.seed:
                actor = admin if index == 0 else contributor
                content = (
                    collection["marker"]
                    + "\nThis synthetic document tests collection access. The blue delivery van arrives at the east gate at nine.\n"
                ).encode()
                status, _ = actor.request(
                    source_base
                    + "/files?"
                    + urlencode({"filename_value": "role-example.txt"}),
                    method="POST",
                    raw=content,
                )
                expect(
                    status == 202,
                    (
                        "admin fixture upload"
                        if index == 0
                        else "contributor permitted upload"
                    ),
                )
        deadline = time.monotonic() + 240
        while True:
            prepared = [
                admin.json(base + "/sources/" + source["id"] + "/assets")
                for source in sources
            ]
            if all(
                rows and rows[0].get("embedding_status") == "indexed"
                for rows in prepared
            ):
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Synthetic fixtures did not finish indexing; inspect local jobs"
                )
            time.sleep(2)
        for client, role in (
            (owner, "owner"),
            (admin, "admin"),
            (viewer, "member"),
            (contributor, "member"),
        ):
            capabilities = client.json(base + "/capabilities")
            expect(capabilities["role"] == role, f"{role} role")
            expect(
                capabilities["can_manage_roles"] == (role == "owner"),
                f"{role} owner-only policy",
            )
            is_admin = role != "member"
            status, _ = client.request(base + "/people")
            expect(status == (200 if is_admin else 403), f"{role} directory boundary")
            status, _ = client.request(base + "/storage")
            expect(status == (200 if is_admin else 403), f"{role} storage boundary")
            state = client.json(base + "/indexes")
            expect(state["can_manage"] == is_admin, f"{role} index capabilities")
            if not is_admin:
                expect(state["generations"] == [], "member sees no index inventory")
                status, _ = client.request(base + "/indexes", method="POST")
                expect(status == 404, "member cannot build index")
                status, _ = client.request(
                    base + "/sources",
                    method="POST",
                    body={"name": "Not allowed", "connector_kind": "local_folder"},
                )
                expect(status == 403, "member cannot import host folders")
        directory = admin.json(base + "/people")["items"]
        expect(
            all(
                account["username"] in {item["username"] for item in directory}
                for account in credentials
            ),
            "owner and three role accounts in directory",
        )
        for index, client in enumerate((viewer, contributor)):
            own, other = sources[index], sources[1 - index]
            own_base = base + "/sources/" + own["id"]
            other_base = base + "/sources/" + other["id"]
            listed = client.json(base + "/sources")
            expect(
                {source["id"] for source in listed} == {own["id"]},
                "member sees only own collection",
            )
            expect(
                listed[0]["can_ingest"] == (index == 1) and not listed[0]["can_admin"],
                "viewer/contributor action distinction",
            )
            own_file, other_file = prepared[index][0], prepared[1 - index][0]
            for suffix in (
                "",
                "/assets",
                "/jobs",
                "/capabilities",
                "/assets/" + other_file["id"] + "/original",
                "/revisions/" + other_file["revision_id"] + "/document",
            ):
                status, _ = client.request(other_base + suffix)
                expect(status == 404, "cross-member content path denied")
            status, original = client.request(
                own_base + "/assets/" + own_file["id"] + "/original"
            )
            expect(
                status == 200 and own["marker"].encode() in original,
                "member can download granted original",
            )
            status, _ = client.request(
                own_base + "/revisions/" + own_file["revision_id"] + "/document"
            )
            expect(status == 200, "member can inspect granted document")
            status, _ = client.request(
                other_base + "/files?filename_value=denied.txt",
                method="POST",
                raw=b"Synthetic denied upload",
            )
            expect(status == 404, "cross-member upload denied")
            if index == 0:
                status, _ = client.request(
                    own_base + "/files?filename_value=denied.txt",
                    method="POST",
                    raw=b"Synthetic denied upload",
                )
                expect(status == 403, "viewer upload denied")
            status, _ = client.request(own_base, method="DELETE")
            expect(status == 403, "member cannot disconnect collection")
            facets = client.json(base + "/search/facets")
            expect(
                all(item["source_id"] == own["id"] for item in facets["items"]),
                "member facets scoped",
            )
            for wanted in (own, other):
                result = client.json(
                    base + "/search",
                    method="POST",
                    body={
                        "workspace_id": payload["workspace_id"],
                        "query": wanted["marker"],
                        "mode": "lexical",
                    },
                )
                if wanted is own:
                    expect(bool(result["results"]), "member finds own fixture")
                    hit = result["results"][0]
                    citation_id = hit["citations"][0]["id"]
                    expect(
                        client.request(own_base + "/citations/" + citation_id)[0]
                        == 200,
                        "member citation resolves",
                    )
                    other_client = contributor if index == 0 else viewer
                    expect(
                        other_client.request(own_base + "/citations/" + citation_id)[0]
                        == 404,
                        "cross-member citation denied",
                    )
                else:
                    expect(not result["results"], "hidden marker produces no results")
        for client in (owner, admin):
            for source in sources:
                result = client.json(
                    base + "/search",
                    method="POST",
                    body={
                        "workspace_id": payload["workspace_id"],
                        "query": source["marker"],
                        "mode": "lexical",
                    },
                )
                expect(
                    any(
                        hit["asset"]["source_id"] == source["id"]
                        for hit in result["results"]
                    ),
                    "workspace administrator finds both fixtures",
                )
        report = {
            "status": "passed",
            "checks": len(checks),
            "coverage": checks,
            "fixture_files": 2,
            "search_mode": "lexical; browser hybrid search checked separately",
        }
        (ROOT / ".local/role-account-validation.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(
            f"Passed {len(checks)} live role-account checks; four account sessions signed out on completion."
        )
    finally:
        for client in clients.values():
            client.request("/auth/logout", method="POST", body={})


if __name__ == "__main__":
    main()
