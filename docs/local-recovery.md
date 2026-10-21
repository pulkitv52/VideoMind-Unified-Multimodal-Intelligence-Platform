# Local backup and recovery

This work adds operational backup commands and a persistent deletion/reinstatement journal to the CPU laptop deployment. It does not change search, embeddings or action retrieval. The original Phase 7 release gate remains open.

## What is protected

`python scripts/backup.py create`, run with `backend/.venv/bin/python`, creates a coordinated PostgreSQL dump and copies every referenced MinIO object. The inventory, relationship counts and dump use the same exported PostgreSQL repeatable-read snapshot. The shared storage system's exclusive maintenance lock prevents object reference writes and reclamation while the snapshot is copied. Authentication records are included, so every backup is private.

The operator verifies the dump checksum and each object's length/checksum, writes a manifest and journal copy, fsyncs file contents and directories, and atomically renames the completed directory. A failure leaves an `.incomplete` directory that is never selected as a completed backup. Bounds are 512 MiB of referenced objects, 2,000 objects, a ten-minute operator deadline and a four-GiB admission budget across local backups. Admission includes existing files, the new dump and prospective object bytes. Interrupted snapshots count toward admission; nothing is automatically deleted to make space.

Backups live under `.local/backups/<backup-id>/`. Database dumps, journal files and logs are mode 0600 inside mode-0700 directories. Checksums detect accidental corruption, not malicious rewriting by a privileged local operator. Preserve `.env`, the repository/lockfiles and the Docker volumes separately; the credential file and model cache are not bundled into each backup.

## Committed deletion journal

Migration `0019_recovery_journal` records asset/source tombstones, reinstatements and hard removals, and workspace removals, in the same PostgreSQL transaction as the change. Rollback rolls back the event. Events have no retention-cascading foreign keys, so removing content does not erase its recovery record. Payloads contain entity IDs, deletion state and timestamps, never document/media content or source credentials. Ordinary runtime users cannot access the `recovery` schema.

The `recovery-journal` Compose service uses operator credentials and copies committed events into a SQLite ledger on the separate `videomind_recovery-data` volume. API, workers and the model do not receive that volume. SQLite uses full synchronous commits, identity-based deduplication, a lineage guard and no high-water sequence cursor that could skip late commits. The service polls every two seconds and becomes unhealthy if its last successful export is older than 30 seconds. The 100,000-event pilot bound fails closed rather than silently dropping records. There is no automatic journal pruning.

This is asynchronous export. It does not promise zero-loss deletion acknowledgement: loss of PostgreSQL before a pending event is exported can lose that event. A separate named volume survives database replacement, but shares the laptop disk. Losing the disk or the journal volume loses that protection. Do not delete volumes with `docker compose down -v`.

## Commands

Run from the project directory:

```bash
backend/.venv/bin/python scripts/backup.py create
backend/.venv/bin/python scripts/backup.py status
backend/.venv/bin/python scripts/backup.py export-journal
backend/.venv/bin/python scripts/backup.py verify --backup-id <12-hex-id>
backend/.venv/bin/python scripts/backup.py drill --backup-id <12-hex-id>
```

`verify` checks saved bytes without contacting the stack. `export-journal` writes a private export of the persistent ledger under `.local` without contacting PostgreSQL; the journal container/volume must still be available. It reports the last successful export age, so a known gap is not mistaken for fresh history. `drill` requires the running stack and creates only a generated `videomind_restore_<id>` database and `vm-restore-<id>` bucket. It never restores the primary. It verifies all restored object bytes and database counts, citation-anchor relationships and runtime isolation, replays the saved journal, then obtains and replays the latest independent journal. Receipts make repeated replay idempotent. It checks that tombstoned assets/sources have no published membership. Both disposable targets are removed on completion or failure.

The latest journal is required because a journal bundled in yesterday's backup cannot contain today's deletions. A lineage mismatch stops replay. Events already represented in the restored snapshot are skipped, and later changes preserve their order, including re-additions. Asset reinstatement does not invent missing generation membership; normal reconciliation would be needed before a real restored service resumes search. Source reinstatement restores `connected` status; transient job status is not reconstructed from a deletion flag.

The new operational commands support snapshots created after migration 0019. The historical Phase 7 rehearsal and its reports remain intact; its older snapshots are not silently treated as current operational backups.

## Schedule and recovery procedure

The local operational target is one verified backup daily while the laptop, Docker stack and scheduler are available. Sleeping/offline machines cannot guarantee a 24-hour RPO. The `VideoMind daily backup` Codex heartbeat is active, scheduled daily at 10:00 in the app's local timezone. It creates and verifies a backup, reports actionable failures, and stays quiet on routine success. The first recurring run has not yet been observed; manual runs were validated below. Backups remain on the same disk; off-device encrypted copies are separate work. No automatic expiry is enabled, so deleted bytes can remain in retained backups until an operator removes those backups. Review space before the four-GiB admission limit is reached.

For an actual incident, keep the application unavailable to users. Preserve/export the latest independent journal and `.env` before replacing any volume. Verify a saved backup, rehearse it in the disposable targets, then have an operator prepare a replacement primary with matching roles/credentials, restore its database and objects, and replay the latest matching journal before reconnecting the API or workers. Recheck access grants, disabled accounts and sessions: this journal covers content deletion/reinstatement, not post-backup permission or credential changes. Reconcile expired jobs and index coverage, verify citations and original bytes, then resume service. The delivered command deliberately does not automate replacement of the primary.

A measured local disposable drill is not a four-hour incident RTO guarantee. The async deletion gap, off-device copy, laptop availability, permission-change replay and real cutover rehearsal remain explicit operational limits.

## Acceptance evidence

The final `python3 scripts/dev.py verify` run passed **193 tests in 154.02 seconds**, with the existing upstream Starlette/httpx deprecation warning. Five focused host-side backup/journal checks also passed. Black checks passed.

The first saved-backup restore verified all **924 objects**, 46 original asset revisions, 197 vectors and 197 citation records, with matching snapshot counts and runtime-role isolation. The post-backup deletion drill added a guarded temporary source and metadata-only asset, included them in a snapshot, disconnected the source through the real authenticated API, and replayed the resulting two committed journal events. In the disposable restored database both tombstones were true and the real runtime role's source-access check was false. Repeated replay applied zero events. The fixture had no original/vector/citation of its own; this check demonstrates source/asset metadata and access replay, alongside the unchanged 197-vector restore. The temporary source was removed afterward. No primary restore occurred.

The exporter restart test preserved all prior event IDs across restart (486 events before, 523 afterward as concurrent integration fixtures committed more events). An actual private offline journal export succeeded without a primary-database sync. The final authenticated corpus verification re-downloaded/checksummed all **46 originals**, confirmed the frozen generation/profile snapshot and preserved labels. Frontend `/health` returned 200 and anonymous `/api/workspaces` returned the expected 401 through localhost:8080.

See [deletion replay evidence](../evaluation/reports/local-recovery-deletion-check.json), [restore evidence](../evaluation/reports/local-recovery-drill.json) and [journal restart evidence](../evaluation/reports/local-recovery-journal-restart.json). The installed automation ID is `videomind-daily-backup`; a manually verified backup exists, but a full day of scheduled operation has not been observed. Original Phase 7 performance and relevance failures remain unchanged.
