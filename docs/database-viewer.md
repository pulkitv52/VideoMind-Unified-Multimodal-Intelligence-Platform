# Browse PostgreSQL with pgAdmin

The optional pgAdmin service provides a browser interface at
[localhost:8081](http://localhost:8081). It replaces Adminer and uses the same
restricted database login and workspace views. The main VideoMind interface
remains at localhost:8080.

Start pgAdmin from the project folder:

```bash
python3 scripts/database_viewer.py
```

The helper provisions the existing read-only database connection, generates a
separate pgAdmin web account and starts the optional `database-viewer` container.
Its image is pinned by digest. The service is bound only to `127.0.0.1:8081` and
PostgreSQL's port remains private. Container setup follows the
[official pgAdmin deployment documentation](https://www.pgadmin.org/docs/pgadmin4/latest/container_deployment.html).

## Sign in and inspect rows

Open [pgAdmin](http://localhost:8081). Copy the **email** and **password** from
`.local/pgadmin.json`. These belong to pgAdmin, not the VideoMind application.
The account label uses `owner@example.com`; it does not send email.

The **VideoMind (read only)** server is registered automatically. Its PostgreSQL
password is configured inside pgAdmin's private data volume, so connecting does
not normally require another password. Expand:

```text
Servers
└── VideoMind (read only)
    └── Databases
        └── videomind
            └── Schemas
                └── browser
                    └── Views
```

Right-click a view such as `sources`, `assets`, `segments`, `embeddings`,
`citation_records`, `ingestion_jobs` or `embedding_jobs`, then choose
**View/Edit Data → First 100 Rows**. Despite that menu name, the database login
has no write privileges. Application tables under `app` and authentication tables
under `auth` are not directly readable with this connection.

## Scope and persistence

The separate `videomind_browser` database role has no superuser, RLS-bypass,
application-table, authentication-table or write privileges. Security-barrier
views restrict rows to one workspace owned by the account in `.local/owner.json`
and require that account to remain enabled and an owner/admin there. This is a
local operator tool: anyone with its pgAdmin credentials can inspect those views.
Global tables without a workspace ID and password/session records are excluded.
Application RLS policies and runtime-role grants are unchanged. Rerun the helper
after adding tables so new applicable views can be provisioned.

Private files are generated under ignored `.local`:

- `pgadmin.json`: pgAdmin web login, mode 0600.
- `pgadmin.env`: bootstrap environment, mode 0600.
- `database-viewer.json`: existing read-only PostgreSQL login, mode 0600.
- `pgadmin-servers.json`: nonsecret connection definition, readable by the container.

The `pgadmin-data` named volume keeps pgAdmin settings and its private `.pgpass`
file (owned by UID 5050, mode 0600). Preserve that volume alongside other named
volumes. Editing `pgadmin.json` alone does not reset an initialized pgAdmin
account's password; use pgAdmin's account settings for that. The helper preserves
existing generated credentials on repeat runs.

The service is optional and does not start during normal `dev.py up`. Once
started it restarts with Docker. Stop only pgAdmin with:

```bash
docker compose --env-file .env -f infra/compose/compose.yaml stop database-viewer
```

The normal `dev.py down` removes this service along with the rest of the stack,
without deleting the named volume or persistent database role/views. Container
HTTP logs are disabled to avoid retaining query URLs. No source files or
application credential files are mounted into pgAdmin.

## Validation

The original workspace-view checks on 24 October 2026 confirmed authorized reads,
foreign-workspace isolation and denial of writes even with the connection's
read-only default disabled. These database grants and view restrictions are
preserved when switching from Adminer to pgAdmin. The pgAdmin replacement passed browser authentication and an authenticated
saved-server connection check without an extra database password. Its saved
connection read the 121 file records through restricted views. Existing-stack
verification passed all 199 tests in 163.62 seconds with the existing
Starlette/httpx warning. Two focused checks cover private credential-file modes,
repeat setup, nonsecret server metadata and environment-injection rejection.
