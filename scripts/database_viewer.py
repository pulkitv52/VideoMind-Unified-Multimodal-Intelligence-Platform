"""Start an optional, loopback-only browser for the local operator's app tables."""

import json
import os
import secrets
import subprocess
import sys

from dev import ROOT, compose, setup

# Security-barrier views expose only the selected owner's workspace. The browser
# login has no grants on app/auth tables and cannot bypass their RLS policies.
PROVISION = """
import json, os, sys
from sqlalchemy import text
from psycopg import sql
from videomind.infrastructure.database import database
payload = json.load(sys.stdin)
engine = database(os.environ["VM_MIGRATION_DATABASE_URL"])
try:
    with engine.begin() as conn:
        owner = conn.execute(text("SELECT p.id,m.workspace_id FROM auth.principals p JOIN app.memberships m ON m.principal_id=p.id WHERE p.username=:name AND NOT p.disabled AND m.role='owner' ORDER BY m.workspace_id LIMIT 1"), {"name":payload["username"]}).first()
        if owner is None:
            raise ValueError("Owner workspace unavailable")
        existing = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='videomind_browser'")).first()
        if existing and not payload["existing"]:
            raise ValueError("Unmanaged browser role already exists")
        if existing:
            known_login = database(engine.url.set(username="videomind_browser", password=payload["password"]).render_as_string(hide_password=False))
            try:
                with known_login.connect() as login:
                    login.exec_driver_sql("SELECT 1")
            finally:
                known_login.dispose()
            if conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='videomind_browser'))")).scalar_one():
                raise ValueError("Browser role has unexpected memberships")
        raw = conn.connection.driver_connection
        if not existing:
            conn.exec_driver_sql(sql.SQL("CREATE ROLE videomind_browser LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD {}").format(sql.Literal(payload["password"])).as_string(raw))
        # Fail closed rather than alter a preexisting privileged account.
        unsafe = conn.execute(text("SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname='videomind_browser'")).scalar_one()
        if unsafe:
            raise ValueError("Browser role has unexpected privileges")
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS browser")
        conn.exec_driver_sql("REVOKE ALL ON SCHEMA browser FROM PUBLIC")
        conn.exec_driver_sql("GRANT CONNECT ON DATABASE videomind TO videomind_browser")
        conn.exec_driver_sql("GRANT USAGE ON SCHEMA browser TO videomind_browser")
        tables = conn.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema='app' AND column_name='workspace_id' ORDER BY table_name")).scalars().all()
        for table in tables:
            statement = sql.SQL("CREATE OR REPLACE VIEW browser.{} WITH (security_barrier=true) AS SELECT t.* FROM app.{} t WHERE t.workspace_id={}::uuid AND EXISTS (SELECT 1 FROM app.memberships m JOIN auth.principals p ON p.id=m.principal_id WHERE m.workspace_id={}::uuid AND m.principal_id={}::uuid AND m.role IN ('owner','admin') AND NOT p.disabled)").format(sql.Identifier(table),sql.Identifier(table),sql.Literal(str(owner.workspace_id)),sql.Literal(str(owner.workspace_id)),sql.Literal(str(owner.id)))
            conn.exec_driver_sql(statement.as_string(raw))
            conn.exec_driver_sql(sql.SQL("GRANT SELECT ON browser.{} TO videomind_browser").format(sql.Identifier(table)).as_string(raw))
        conn.exec_driver_sql("ALTER ROLE videomind_browser SET default_transaction_read_only = on")
        conn.exec_driver_sql("ALTER ROLE videomind_browser SET search_path = browser, pg_catalog")
        conn.exec_driver_sql("ALTER ROLE videomind_browser SET statement_timeout = '10s'")
        conn.exec_driver_sql("ALTER ROLE videomind_browser SET idle_in_transaction_session_timeout = '30s'")
    viewer = database(engine.url.set(username="videomind_browser", password=payload["password"]).render_as_string(hide_password=False))
    try:
        with viewer.connect() as conn:
            assert conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
            conn.exec_driver_sql("SELECT count(*) FROM browser.assets").scalar_one()
            assert not conn.exec_driver_sql("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user").scalar_one()
        from sqlalchemy.exc import DBAPIError
        for statement in ("SELECT * FROM auth.principals LIMIT 0", "SELECT * FROM auth.sessions LIMIT 0", "SELECT * FROM app.assets LIMIT 0", "UPDATE browser.assets SET title=title WHERE false"):
            with viewer.connect() as conn:
                try:
                    conn.exec_driver_sql(statement)
                except DBAPIError as exc:
                    if exc.orig.sqlstate not in ("42501", "25006"):
                        raise
                else:
                    raise ValueError("Browser unexpectedly allowed a restricted operation")
    finally:
        viewer.dispose()
finally:
    engine.dispose()
"""


def prepare_pgadmin():
    path = ROOT / ".local/pgadmin.json"
    if path.exists():
        credentials = json.loads(path.read_text())
    else:
        credentials = {
            "url": "http://localhost:8081",
            "email": "owner@example.com",
            "password": secrets.token_urlsafe(24),
        }
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(credentials, output, indent=2)
            output.write("\n")
    if not all(
        isinstance(credentials.get(key), str)
        and credentials[key]
        and not any(char in credentials[key] for char in "\r\n")
        for key in ("email", "password")
    ):
        raise ValueError("Invalid local pgAdmin credentials")
    path.chmod(0o600)
    environment = ROOT / ".local/pgadmin.env"
    descriptor = os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(
            f"PGADMIN_DEFAULT_EMAIL={credentials['email']}\nPGADMIN_DEFAULT_PASSWORD={credentials['password']}\n"
        )
    environment.chmod(0o600)
    servers = {
        "Servers": {
            "1": {
                "Name": "VideoMind (read only)",
                "Group": "Servers",
                "Host": "postgres",
                "Port": 5432,
                "MaintenanceDB": "videomind",
                "Username": "videomind_browser",
                "ConnectionParameters": {"sslmode": "prefer", "passfile": ".pgpass"},
            }
        }
    }
    server_file = ROOT / ".local/pgadmin-servers.json"
    server_file.write_text(json.dumps(servers, indent=2) + "\n")
    server_file.chmod(
        0o644
    )  # Nonsecret connection metadata read by container UID 5050.
    return credentials


def main():
    setup()
    try:
        pgadmin_credentials = prepare_pgadmin()
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit(
            "Could not prepare private pgAdmin settings; no credentials were printed."
        )
    path = ROOT / ".local/database-viewer.json"
    existing = path.exists()
    try:
        if existing:
            credentials = json.loads(path.read_text())
            password = credentials["password"]
            if not isinstance(password, str) or not password:
                raise ValueError()
        else:
            password = secrets.token_urlsafe(24)
            credentials = {
                "url": "http://localhost:8081",
                "system": "PostgreSQL",
                "server": "postgres",
                "username": "videomind_browser",
                "password": password,
                "database": "videomind",
            }
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(credentials, output, indent=2)
                output.write("\n")
        path.chmod(0o600)
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit(
            "Could not prepare private viewer credentials; no credentials were printed."
        )

    try:
        owner = json.loads((ROOT / ".local/owner.json").read_text())["username"]
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit("Could not identify the local owner account.")

    command = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "infra/compose/compose.yaml"),
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "bootstrap",
        "python",
        "-c",
        PROVISION,
    ]
    result = subprocess.run(
        command,
        input=json.dumps(
            {"password": password, "existing": existing, "username": owner}
        ),
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    if result.returncode:
        sys.exit(
            "Viewer account setup or privilege checks failed. Check the running database; no credentials were printed."
        )
    compose(
        "up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "database-viewer"
    )
    # pgpass must be owned by UID 5050 and mode 0600; keep it inside pgAdmin's volume.
    passfile_writer = r"""
import json, os, sys, sqlite3
from pathlib import Path
payload = json.load(sys.stdin)
with sqlite3.connect('/var/lib/pgadmin/pgadmin4.db') as connection:
    row = connection.execute('SELECT username FROM user WHERE email=?', (payload['email'],)).fetchone()
    if not row:
        raise ValueError('pgAdmin account unavailable')
    username = row[0]
    if not username or username[0].isdigit():
        username = 'pga_user_' + username
    username = username.replace('@', '_').replace('/', 'slash').replace(chr(92), 'slash')
    directory = Path('/var/lib/pgadmin/storage') / username
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / '.pgpass'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('postgres:5432:videomind:videomind_browser:' + payload['password'] + '\n')
    servers = connection.execute("SELECT id,connection_params FROM server WHERE name='VideoMind (read only)' AND host='postgres' AND username='videomind_browser'").fetchall()
    for sid, parameters in servers:
        params = json.loads(parameters or '{}')
        params.update({'sslmode': 'prefer', 'passfile': '.pgpass'})
        connection.execute('UPDATE server SET connection_params=? WHERE id=?', (json.dumps(params), sid))
    if not servers:
        raise ValueError('Saved VideoMind server unavailable')
Path('/var/lib/pgadmin/.pgpass').unlink(missing_ok=True)
"""
    passfile = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "infra/compose/compose.yaml"),
            "exec",
            "-T",
            "database-viewer",
            "/venv/bin/python3",
            "-c",
            passfile_writer,
        ],
        input=json.dumps({"password": password, "email": pgadmin_credentials["email"]}),
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    if passfile.returncode:
        sys.exit(
            "pgAdmin started but the saved database login could not be prepared. No credentials were printed."
        )
    print("pgAdmin: http://localhost:8081")
    print(
        "pgAdmin login details: .local/pgadmin.json (separate from the application login)"
    )
    print(
        "Read-only views in the browser schema show your owner workspace; app and auth tables are protected."
    )


if __name__ == "__main__":
    main()
