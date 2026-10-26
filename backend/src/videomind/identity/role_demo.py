"""Operator-only, explicit provisioning of three persistent role-test accounts."""

import argparse
import json
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

from sqlalchemy import text

from videomind.identity.security import password_hash, verify_password
from videomind.infrastructure.database import database

ACCOUNTS = (
    ("demo_admin", "admin"),
    ("demo_member_viewer", "member"),
    ("demo_member_contributor", "member"),
)


def provision(engine, workspace: UUID, credential_file: Path):
    """Fail on name collisions; never adopt accounts or rotate existing credentials."""
    if credential_file.is_symlink():
        raise ValueError("Credential path must not be a symlink")
    if credential_file.exists():
        payload = json.loads(credential_file.read_text())
        if payload["workspace_id"] != str(workspace):
            raise ValueError("Credential file belongs to another workspace")
        with engine.connect() as conn:
            for account, (username, role) in zip(
                payload["accounts"], ACCOUNTS, strict=True
            ):
                row = (
                    conn.execute(
                        text(
                            "SELECT p.id,p.password_hash,p.disabled,m.role FROM auth.principals p JOIN app.memberships m ON m.principal_id=p.id WHERE p.username=:name AND m.workspace_id=:w"
                        ),
                        {"name": username, "w": workspace},
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    not row
                    or str(row["id"]) != account["id"]
                    or row["role"] != role
                    or row["disabled"]
                    or account["username"] != username
                    or not verify_password(account["password"], row["password_hash"])
                ):
                    raise ValueError("Demo accounts changed; operator review required")
            for collection in payload["collections"]:
                row = conn.execute(
                    text(
                        "SELECT deleted FROM app.sources WHERE workspace_id=:w AND id=:s"
                    ),
                    {"w": workspace, "s": collection["id"]},
                ).first()
                grant = conn.execute(
                    text(
                        "SELECT permission FROM app.source_grants WHERE workspace_id=:w AND source_id=:s AND principal_id=:p"
                    ),
                    {
                        "w": workspace,
                        "s": collection["id"],
                        "p": collection["member_id"],
                    },
                ).scalar_one_or_none()
                if not row or row.deleted or grant != collection["permission"]:
                    raise ValueError(
                        "Demo collection access changed; operator review required"
                    )
        credential_file.chmod(0o600)
        return payload
    payload = {"workspace_id": str(workspace), "accounts": [], "collections": []}
    created_file = False
    try:
        with engine.begin() as conn:
            if not conn.execute(
                text("SELECT id FROM app.workspaces WHERE id=:w FOR UPDATE"),
                {"w": workspace},
            ).first():
                raise ValueError("Workspace unavailable")
            for username, role in ACCOUNTS:
                if conn.execute(
                    text("SELECT id FROM auth.principals WHERE username=:name"),
                    {"name": username},
                ).first():
                    raise ValueError(
                        "A demo username is already in use; no accounts were changed"
                    )
                principal, password = uuid4(), secrets.token_urlsafe(24)
                conn.execute(
                    text(
                        "INSERT INTO auth.principals(id,username,password_hash) VALUES(:p,:name,:hash)"
                    ),
                    {"p": principal, "name": username, "hash": password_hash(password)},
                )
                conn.execute(
                    text(
                        "INSERT INTO app.memberships(workspace_id,principal_id,role) VALUES(:w,:p,:role)"
                    ),
                    {"w": workspace, "p": principal, "role": role},
                )
                payload["accounts"].append(
                    {
                        "id": str(principal),
                        "username": username,
                        "password": password,
                        "role": role,
                    }
                )
            for index, (name, permission, marker) in enumerate(
                (
                    ("Role test — Viewer", "read", "ROLE-VIEWER-ALPHA"),
                    ("Role test — Contributor", "ingest", "ROLE-CONTRIBUTOR-BETA"),
                ),
                start=1,
            ):
                source, member = uuid4(), payload["accounts"][index]["id"]
                conn.execute(
                    text(
                        "INSERT INTO app.sources(workspace_id,id,name,connector_kind,status) VALUES(:w,:s,:name,'upload','connected')"
                    ),
                    {"w": workspace, "s": source, "name": name},
                )
                conn.execute(
                    text(
                        "INSERT INTO app.source_grants(workspace_id,source_id,principal_id,permission) VALUES(:w,:s,:p,:permission)"
                    ),
                    {
                        "w": workspace,
                        "s": source,
                        "p": member,
                        "permission": permission,
                    },
                )
                payload["collections"].append(
                    {
                        "id": str(source),
                        "name": name,
                        "member_id": member,
                        "permission": permission,
                        "marker": marker,
                    }
                )
            credential_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            created_file = True
            with os.fdopen(descriptor, "w") as output:
                json.dump(payload, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        return payload
    except Exception:
        if created_file:
            credential_file.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    args = parser.parse_args()
    engine = database(os.environ["VM_MIGRATION_DATABASE_URL"])
    try:
        provision(engine, args.workspace, args.credential_file)
        print(
            "Role-test accounts are ready. Read the private credential file to sign in."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
