# Upload and local-folder intake

Scope authorized on 18 October 2026: add usable file/folder source controls and exercise a small dataset on the CPU-only laptop. This document records the original intake milestone; Phase 2 completion and current behavior are recorded in [phase2-validation.md](phase2-validation.md). Extraction, OCR, transcription, segmentation, model embeddings and semantic search retain their later phase gates.

## User flow

Refresh http://localhost:8080 after updating. Choose **Add source**, give it a name, select **Upload files**, and create it. The collection has an **Upload files** control that accepts multiple files. Uploads run sequentially in the browser; each file is preserved and validated asynchronously. Clicking a filename downloads its authenticated original. Status distinguishes queued/running, validated-but-not-indexed, and failed intake. Failed jobs have a retry action.

Supported file extensions: PDF, DOCX, UTF-8 TXT/Markdown, PNG/JPEG, MP4/WebM, MP3/WAV/M4A/FLAC/Ogg. There is a 64 MiB per-file limit and two simultaneous server uploads. Limits are checked on bytes received even without Content-Length. Admission checks signatures, UTF-8 and DOCX archive budgets; an isolated, time-limited worker checks document/image structure or media tracks and an initial decodable frame. This does not guarantee that every frame/page of a damaged file is usable. SVG, arbitrary archives, executable files, and macro-enabled Office files are unsupported.

For a local folder, place files under `.local/imports/<name>` on the host, then select **Local folder (read only)** in the form. Only the operator's import area is mounted into containers, read-only. Relative traversal, symlinks and non-regular/hardlinked entries are rejected. Keep this area free of private content that should not be available to local workspace administrators. A scan is limited to 200 files, 256 MiB total and 180 seconds. Unsupported entries stop the scan with a visible error; metadata/attribution should use supported TXT/Markdown files. **Sync folder** is explicit; this release does not continuously watch filesystem changes.

Syncing identical bytes preserves revision identities. Changed bytes create an immutable revision; a complete scan tombstones missing files. A failed/partial scan does not run deletion reconciliation. Existing historical revisions with identical bytes can be reused when a file reverts. Disconnect hides the source and files immediately and cancels pending work. Automatic physical retirement now follows a one-hour retention floor; see the Phase 2 completion record. The laptop's originals are untouched.

File lists now use cursor pagination with a Load more action. Workspace quotas include revision history and pending upload reservations; current defaults and limits are documented in the Phase 2 completion record.

## Modules and persistence

- `connectors/upload/validation.py`: filename, signature, UTF-8 and ZIP admission.
- `connectors/local_folder/reader.py`: descriptor-relative, no-follow folder reads.
- `connectors/routes.py`: authenticated source creation, upload, sync, status, retry and original download.
- `ingestion/service.py`: connector envelopes, hashes, immutable object/revision registration and fenced completion.
- `ingestion/dispatcher.py`: PostgreSQL-driven queue reconciliation every five seconds, independently of Redis scheduler state.
- `ingestion/worker.py`: leased validation and folder-sync tasks.
- `preprocessing/probe.py`: bounded format probing in a child process. It does not extract searchable content.

The new `ingestion_jobs` table is source-scoped with forced RLS. `latest_revision_id` identifies received originals separately from `current_revision_id`, which remains reserved for search publication. Standalone image assets and image filter/evidence contract values were added at the user's request.

PostgreSQL atomically records accepted revision/job/stage/outbox rows after an immutable object write. The dispatcher inventories only queued/expired job identifiers through narrow internal SQL functions; workers claim one attempt transactionally, then use the requesting principal's current access scope. Claims check disabled users, source tombstones, current membership/grants and the three-attempt cap. Five-minute leases, fenced completion and source-scoped transaction locks prevent superseded task completion and source resurrection. Repeated dispatch is expected and safe. Outbox delivery is confirmed when a worker claims the corresponding run. Permanent validation failures are terminal until a user retries; transient failures back off for fifteen seconds.

The scheduler inventory/claim functions are trusted server internals, not content APIs. They use fixed search paths, revoke PUBLIC execution, and are not a mechanism for untrusted SQL access. The runtime job policies still bind inserts/updates to the requesting actor. A separate, narrow source-admin function cancels pending jobs for disconnect, including those submitted by another member; it does not grant general job update/delete rights.

The Compose dispatcher is a seventh lightweight service. The validation worker remains solo; parser subprocesses have a 30-second wall timeout and 20-second CPU limit. Docker memory/temp-storage limits remain in effect. Heavy inference is not loaded. Linux host networking is used **during dependency builds only**, following repeated bridge-network download timeouts; application containers retain the private Compose network and loopback-only published ports. Dependency cache mounts and longer download timeouts reduce repeat downloads.

## Datasets and reproducibility

[Dataset research](research/local-mvp-datasets.md) records licenses, exact URLs, sizes and evaluation limitations. Two public samples total 681,556 bytes: the ESC-10 dog recording and scikit-image's Chelsea cat image. Public source credits are preserved in the manifest and an uploaded attribution document. Synthetic fixtures add scanned PDF, DOCX, procedure text, speech/beeps and silent/spoken MP4s.

```bash
python3 scripts/fetch_starter_data.py
python3 scripts/demo_intake.py
python3 scripts/dev.py verify
python3 scripts/check_intake_faults.py
```

The demo expects the Phase 0 generated fixtures, including the renderer DOCX; generation instructions remain in `evaluation/README.md`. It creates/reuses **Starter dataset** and **Local starter folder** in the bootstrap owner's workspace. The fault script creates and tombstones only disposable verification sources and briefly restarts this project's worker/Redis.

Evidence reports:

- `evaluation/reports/phase2-starter-intake.json`: ten uploads passed structural checks and exact original checksum round trips; repeated upload was a no-op; three folder files retained revision IDs on resync. The first run completed in 20.67 seconds, including polling. This is not an ingestion-throughput or retrieval benchmark.
- `evaluation/reports/phase2-faults.json`: changed-folder revision, missing-file tombstone, symlink rejection, queued work across worker/Redis restart, expired lease reclaim and rejection of stale completion.
- The running UI was checked using source creation and a two-file chooser upload. Disposable browser fixtures are removed afterward.

The full live suite passed **60 tests in 27.64 seconds**, covering current runtime-role isolation, upload rejection, corrupt-PDF failure/retry, immutable revisions, source tombstones, ordinary ingest grants and narrow multi-user cancellation. Strict TypeScript and the Vite production build passed; one upstream TestClient/httpx deprecation warning remains. The browser source-creation and two-file upload passed. Final readiness is true for all four dependencies, with retrieval readiness correctly false. See `evaluation/reports/intake-validation.json` and `evaluation/reports/intake-ui.png`.

The seven services used about **450.6 MiB** in one post-test Docker memory snapshot, with no model loaded. This is neither peak memory nor a combined inference benchmark. Individual limits and raw accounting are in the report.

## Phase 2 completion

The remaining connector adapters/cursors, orphan cleanup, retention, process-kill fault matrix, workspace quotas and file/job pagination are implemented. See [Phase 2 validation](phase2-validation.md) and `evaluation/reports/phase2-completion.json` for current acceptance evidence and operating limits. Earlier test counts and snapshots above describe the intake milestone, not the final suite.

No files are marked searchable, no query quality metrics were measured, and no GPU was used. Document extraction/evidence viewing remains Phase 3; audio/video processing, embeddings and search retain their later phase gates.
