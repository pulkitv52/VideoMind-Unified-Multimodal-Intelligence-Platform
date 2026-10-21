# Phase 2: connectors and durable ingestion

The user authorized completion of Phase 2 on 19 October 2026. This completes file/folder intake on the existing CPU-only laptop. Document extraction, OCR, ASR, embeddings, semantic search and media playback retain their later phase gates.

## Delivered behavior

Uploads and allowlisted read-only folders implement the Connector contract: configuration validation, capability reporting, paged discovery and revision-checked streaming fetch. Uploads are explicit receipts. Folders use bounded full-manifest scans, not incremental filesystem watches. Discovery returns a content-hash revision, MIME, byte size and inherited source permissions. Local folders preserve observed file modification time; browser uploads leave unknown original timestamps unset. Fetch rejects changed bytes, size or observed file metadata. Unsupported item ACL modes fail closed.

A folder's page cursor belongs to one in-memory scan. A restarted job scans again and reuses registered revisions. The durable source cursor is the completed manifest fingerprint, committed with deletion reconciliation only after all fetched items have durable registrations. A partial failure keeps prior source membership and the prior completed cursor. Individual files registered before failure remain durable and are reused on retry. Job progress persists in PostgreSQL, including after failure.

Originals, revisions, validation jobs, stage state and outbox events are registered transactionally. PostgreSQL leases fence stale delivery, manual retry and late completion. A database trigger keeps job, stage and processing-run states consistent during claim, retry, attempt exhaustion, cancellation and completion. Redis deliveries are reconstructible from PostgreSQL even after a message is lost. Validation completion still means **stored and format-validated**, with `searchable=false`.

## Storage and retention

The default workspace admission budget is **5 GiB and 10,000 objects**, including immutable revision history and pending upload reservations. Configuration uses `VM_WORKSPACE_STORAGE_BYTES` and `VM_WORKSPACE_STORAGE_OBJECTS`. A workspace lock serializes admission across sources. Identical filename/content submissions remain no-ops at quota; new versions consume additional storage. Only workspace administrators can view aggregate usage; members cannot use that endpoint to inspect private-source totals.

A quota reservation commits before any object bytes are written. The subsequent object reference and reservation removal commit together. A failed PUT or killed process leaves the reservation charged until cleanup confirms object removal. Reservations intentionally survive source deletion. These are application admission quotas; host caches, downloaded evaluation archives, PostgreSQL files and provider overhead are separate disk use.

The 64 MiB per-file limit and two API upload slots remain in effect. Each bounded original uses a single PUT; no persistent multipart-upload session is created. SDK buffering is bounded by the file cap. API and worker temporary files stay on size-limited container tmpfs. Restarting a killed application container discards its temporary mount; durable originals and jobs remain in MinIO/PostgreSQL.

Writers hold a shared storage lock over object write and reference commit. The dispatcher takes the exclusive form for maintenance and skips a busy batch. It reclaims expired failed-write reservations, retires disconnected sources and removed folder assets after a fixed one-hour floor, and sweeps at most 32 inventory keys per pass. Active revision history remains referenced and is preserved. A durable inventory cursor makes scans restartable; repeated removals are idempotent. Recent unreferenced objects receive a one-hour grace period.

Metadata retirement commits before the inventory-removal batch. A failure after metadata retirement leaves reclaimable storage; a failed removal leaves the cursor unadvanced. Source authorization denies content immediately after disconnect. Physical cleanup follows the retention floor and sweep, while the stack and storage are available. The 24-hour local cleanup target assumes the small corpus and running services; it is not an outage or large-corpus SLA. Backup expiry/replay is Phase 7 work.

Maintenance SQL functions are trusted server internals with fixed search paths and PUBLIC execution revoked. `storage_sweep` has forced RLS and no direct runtime table grants. Reservations have source-scoped RLS and immutable runtime metadata. Maintenance functions have no HTTP endpoint. Like the scheduler functions, they assume application database credentials and arbitrary SQL remain operator/server privileges.

## Pagination and bounded work

Asset and job endpoints accept `limit` from 1 to 200 and an `after` UUID. They retain array responses for existing clients and return `X-Next-Cursor`; assets also return `X-Total-Count`. Cursors resolve only inside the authorized workspace/source. These are live inventory pages, not a frozen search result set. Concurrent additions/deletions may change subsequent pages.

The UI reads 50 files at a time and offers **Load more files** when needed. Polls do not overlap. Folder status requests fetch only the latest folder-sync job; file status comes from its own revision job. Administrators see workspace storage usage. Disconnect describes the one-hour cleanup floor.

Asset listing uses bounded batch lookups under the runtime role, with RLS on each table. The earlier join plan repeatedly scanned protected rows: a disposable 205-file case took 17,549.426 ms in EXPLAIN ANALYZE. It was replaced rather than weakening authorization. Supporting indexes cover file/job pagination and enforce one validation job per revision. This diagnostic is not a search benchmark.

Folder scans retain the 200-file, 256 MiB and 180-second bounds. Directory traversal is also bounded to 1,000 visited directories and depth 16, including empty trees. Descriptor-relative reads reject traversal, symlinks, hardlinks and non-regular files. Ordinary source mutations are detected, but this is not an atomic filesystem snapshot; keep operator import folders stable during sync.

## Verification

Run from the repository root:

```bash
python3 scripts/dev.py up
python3 scripts/dev.py verify
python3 scripts/check_intake_faults.py
```

The verification suite uses disposable accounts/sources and real PostgreSQL, runtime-role RLS, HTTP sessions and MinIO. Process-kill cases send actual SIGKILL in isolated child processes. Retention tests advance only disposable fixture timestamps; no 24-hour wall-clock soak is claimed. Broker-loss testing deletes only a uniquely named fixture queue, then reconstructs delivery from PostgreSQL; it does not flush the user's Redis database. The operational fault script briefly restarts only this project's worker and Redis and restores them afterward.

Exit criteria and final measurements are recorded in `evaluation/reports/phase2-completion.json`. This phase does not publish searchable evidence or measure retrieval quality. Completed checks cover the tested boundaries, not arbitrary kernel/filesystem/provider failures or future extraction/model stages.

## Completed release check

The final Compose configuration passed **82 tests in 76.49 seconds**, including the final hardlink/FIFO and HTTP-overflow checks. This includes fresh-database migration to `0007_intake_indexes`, forced-RLS/runtime-role checks and the fault cases above. One upstream Starlette TestClient/httpx deprecation warning remains. Strict TypeScript and the Vite production build passed.

The browser confirmed storage usage, ready services and pagination from 50 to 51 files. Its 51-file fixture validated successfully and was disconnected afterward. Authenticated checksum verification preserved all **46 existing files**, including the **30 dataset videos**, across the five retained collections. Worker/Redis restart and lease-fencing operational checks also passed.

Final readiness was true for every dependency; retrieval readiness remained false. The seven running services used **455.08 MiB** in one post-verification Docker snapshot with no inference model loaded. This is not peak memory or a combined inference measurement. The machine used no GPU. Raw results are linked in the acceptance report.
