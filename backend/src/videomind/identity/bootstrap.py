"""Operator-only account bootstrap. Never exposed as an HTTP endpoint."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets

from sqlalchemy import text

from videomind.identity.security import password_hash
from videomind.infrastructure.database import database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="owner")
    parser.add_argument("--workspace", default="My knowledge")
    parser.add_argument("--credential-file", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", args.username):
        parser.error("invalid username")
    engine = database(os.environ["VM_MIGRATION_DATABASE_URL"])
    try:
        with engine.begin() as conn:
            if conn.execute(
                text("SELECT id FROM auth.principals WHERE username=:name"),
                {"name": args.username},
            ).first():
                print("Account already exists; credentials were left unchanged")
                return
            password = secrets.token_urlsafe(20)
            principal = conn.execute(
                text(
                    "INSERT INTO auth.principals(username,password_hash) VALUES (:name,:hash) RETURNING id"
                ),
                {"name": args.username, "hash": password_hash(password)},
            ).scalar_one()
            workspace = conn.execute(
                text("INSERT INTO app.workspaces(name) VALUES (:name) RETURNING id"),
                {"name": args.workspace},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO app.memberships(workspace_id,principal_id,role) VALUES (:w,:p,'owner')"
                ),
                {"w": workspace, "p": principal},
            )
            args.credential_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                args.credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w") as output:
                json.dump({"username": args.username, "password": password}, output)
                output.write("\n")
        print("Local account created; read the private credential file to sign in")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
