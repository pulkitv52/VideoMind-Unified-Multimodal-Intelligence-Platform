# Phase 1 validation

Validated on 18 October 2026 on the existing Ubuntu x86_64 laptop, AMD Ryzen 7 7730U, 15 GiB usable RAM. The user selected local CPU development and deferred GPU/scaling work. Phase 2 remains unstarted.

## Delivered

- Modular FastAPI backend and React/TypeScript/Vite frontend, uv/pnpm lockfiles and pinned container base images.
- Docker Compose PostgreSQL/pgvector, private MinIO, Redis, API, solo Celery worker and frontend. One-shot migration, private-storage initialization and owner bootstrap jobs.
- Generated private service credentials, salted scrypt password hashes, opaque expiring sessions, login throttling, logout and origin checks. A bootstrap owner has an empty workspace; additional users are operator-created, not self-registered.
- Twenty-three application tables covering workspace/source access, objects, assets/revisions, processing stages/outbox, segments, evidence, embedding profiles/generations, vectors, text search, citations and audit identities. Authentication principals/sessions are separate server-only tables.
- Forced RLS on all application tables, using a runtime role that is neither owner, superuser nor BYPASSRLS. Composite references preserve workspace/source scope. Evidence links require matching revisions and typed locator bounds. Append-only fact tables reject runtime updates.
- Content-free JSON request logs, validated UUID correlation headers and Celery trace-header propagation. Resource limits, actual dependency readiness checks and persistent named volumes.
- Working browser sign-in, authorized workspace/source listing, honest empty state, service status and sign-out.

## Acceptance evidence

| Criterion | Result |
|---|---|
| Start from empty local volumes | Passed on this host; initial migrations and private storage initialized from newly created VideoMind volumes. Repeat `up` preserves account/credentials. |
| Reproducible dependency setup | Application/verification Docker builds and frozen uv/pnpm installs passed. A separate clean host was not available for testing. |
| Migrate an empty database | Passed: integration suite creates a disposable PostgreSQL database, applies all migrations and checks 23 application tables and the head revision. |
| Actual runtime-role isolation | Passed for three users, two workspaces and private/shared/foreign sources. All 17 source-scoped tables tested, including vectors, snippets, evidence, jobs, citations and audit rows. Six workspace-level tables also checked. |
| Connection reuse and identity | Passed: transaction-local actor clears on a reused pooled connection; an HTTP `X-Actor-ID` cannot select another identity; missing/hidden sources share a 404 response. Anonymous content requests return 401. |
| Permission changes | Passed: existing sessions lose access after source-grant or membership revocation. Read-only grants cannot write, and cross-scope references/scope changes fail. |
| Evidence and cleanup | Passed: incomplete page locators and updates to immutable evidence are rejected. Fixture workspace deletion cleans up citation references. |
| Private storage | Authenticated SDK write/read succeeds; anonymous object GET returns 403. Repeated initialization succeeds. |
| Secrets | Real credentials are generated into ignored private files, not checked-in source. Validation errors redact submitted passwords; settings and SQLAlchemy exceptions hide credentials/parameters. |
| Restart persistence | Passed: existing HTTP session and workspace rows remain valid; Redis marker and exact MinIO object bytes survive service restart. |
| Readiness failure/recovery | Passed: Redis stopped → HTTP 503; restarted → all four dependency checks true. Liveness is separate. |
| Browser behavior | Passed: disposable account signs in to its empty workspace, shows ready services and signs out. Test account/workspace removed afterward. |
| Tests and build | 54 backend/integration tests passed in 10.88 s. Frontend strict TypeScript and production build passed. One upstream TestClient/httpx deprecation warning remains. |
| Trace propagation | HTTP correlation and Celery signal propagation checked; ingestion tasks do not exist yet, so a production ingestion trace has not been measured. |

The raw sanitized operational snapshot is [phase1-2026-10-18.json](../evaluation/reports/phase1-2026-10-18.json). The browser capture is [phase1-workspace.png](../evaluation/reports/phase1-workspace.png). All browser/evaluation content was synthetic.

## Versions and memory

Actual running database: **PostgreSQL 16.15**, **pgvector 0.8.7**. Migration head: `0003_citation_cleanup`. Exact image digests are in `infra/compose/compose.yaml` and Dockerfiles; Python/frontend dependencies are in their lockfiles.

| Service | Snapshot memory | Container limit |
|---|---:|---:|
| API | 94.79 MiB | 384 MiB |
| Frontend | 4.22 MiB | 64 MiB |
| MinIO | 60.17 MiB | 512 MiB |
| PostgreSQL | 22.27 MiB | 512 MiB |
| Redis | 3.86 MiB | 128 MiB |
| Worker | 59.17 MiB | 256 MiB |
| Total | **244.48 MiB** | **1,856 MiB** |

These are Docker's memory-accounting values in one post-check snapshot with no ingestion/inference work; they are not peak RSS or reserved RAM. Container limits exclude one-shot build/test/setup jobs, Docker/OS overhead and other laptop applications. The host reported 6.88 GiB available RAM and 1.68 GiB of swap in use at capture time; this does not establish that VideoMind caused swapping.

Phase 0 separately measured the real embedding model at roughly 4.63 GiB peak process RSS. It was not loaded during this foundation run. Combined inference-plus-stack peak memory, query latency under ingestion and long media processing remain future measurements. No GPU is needed to run Phase 1, and no GPU was used.

## Adopted details and limitations

- Identity uses a trusted server-only runtime role plus transaction-local actor UUIDs. RLS defends content queries; it does not make arbitrary SQL access safe. Runtime authentication tables contain password hashes/session records and are not exposed through content routes.
- Local HTTP is bound to loopback. Cookies are HttpOnly/SameSite Strict; secure cookies require a separate TLS deployment. Provider item ACLs and public account registration are deferred. Unsupported item-ACL modes are rejected.
- MinIO's application identity is bucket-scoped. Per-user object access will be mediated by future evidence/media endpoints; neither MinIO nor its console is published.
- Migrations 0002/0003 correct deletion behavior discovered by integration checks: non-cascading cross-branch references validate at commit; citation identities cascade with their evidence. Logical reference integrity remains mandatory at transaction commit. Whole workspace/source hard deletion is operator-only today.
- Schema presence does not implement durable ingestion, immutable object upload protocols, leases/outbox dispatch, generation publication, provenance cycle checks, retrieval or playback. Those behaviors retain their own later-phase acceptance gates. There is no fake search or upload control.
- The worker uses a solo pool and one concurrent job. Celery hard/soft time limits cannot interrupt a solo task; future processing must use subprocess deadlines and durable leases. Readiness currently pings an idle worker; heavy inference will need its separate service and suitable health semantics.
- Dependencies are checked with bounded client timeouts; Redis is persistent for this test, but PostgreSQL remains the intended durable job authority. Redis-loss reconciliation is Phase 2 work.

To reproduce, run `python3 scripts/dev.py up`, `python3 scripts/dev.py verify`, then `python3 scripts/check_foundation.py`. The last command restarts only this Compose project and briefly stops Redis; it replaces the operational report with the latest measurements.

Next authorized milestone requires a user request: Phase 2 upload/local-folder connectors, immutable originals/revisions and durable ingestion orchestration.
