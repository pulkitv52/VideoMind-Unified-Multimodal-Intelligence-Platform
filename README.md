# VideoMind

Unified search across documents, video and audio, developed in phases for a CPU-only laptop.

Phase 0 validated the pinned multimodal model on CPU. Phase 1 provides local infrastructure, sign-in, workspace/source authorization and persistence. Phase 2 adds upload collections, revision-checked read-only local folders, immutable originals, durable validation jobs, storage quotas, retention/orphan cleanup and paginated file lists. Phase 3 adds document extraction, scanned/mixed-page OCR, DOCX rendering and a citation viewer. Phase 4 adds native media windows, local ASR, mapped playback and temporal citations. Phase 5 adds native embeddings, profile-isolated pgvector indexes and generation management. Phase 6 adds authorized hybrid search and evidence results. Phase 7 adds local evaluation and restore rehearsal tools; the MVP release gate remains open.

## Start locally

Requirements: Linux, Python 3.12+, Docker Engine with Compose v2, Internet access for the first image/package download, and free ports 8080/8000. The measured development machine has 16 GiB RAM. Docker runs the application dependencies; a host Node installation is optional.

```bash
python3 scripts/dev.py up
```

Open [VideoMind](http://localhost:8080). Read the generated username/password from `.local/owner.json` locally and enter them in the sign-in form. The setup creates one owner and a workspace. Choose **Add source → Upload files → Create source**, then **Upload files** to select files from your laptop. For read-only folder sync, place files under `.local/imports/<folder>` and choose that folder when creating a source. See [format limits and validation](docs/phase2-validation.md). Documents extract automatically after validation. Choose **Open document**, then select a passage to inspect its region and copy a stable citation. [Document limits and evidence behavior](docs/phase3-validation.md) cover the 50-page, three-minute laptop budget. Choose **Open media** to play a video/audio file and select timeline evidence or transcript words. Processing supports media up to five minutes; see [media limits and validation](docs/phase4-validation.md). Repeating the command preserves the account and credentials.

The **Embedding index** panel shows coverage and failed jobs. Administrators can build a generation, activate it after all eligible inputs are embedded, retry failures and restore a caught-up previous generation. **Open image** displays a standalone image and its citation. Indexing runs in the background on CPU; uploaded content is processed into both the active and building generations. Use **Search your sources** to describe a passage, visual event or sound. Source/type and advanced filters narrow results. **Open evidence** opens the cited page or original-time interval; **More from this file** searches within the matched asset. See [search behavior, limits and validation](docs/phase6-validation.md). See [Phase 5 limits and validation](docs/phase5-validation.md).

`.env` is generated with random service passwords and mode 0600; `.local` is private and ignored. Preserve both alongside your Docker volumes. Changing an environment password alone does not rotate credentials in an existing database/storage service. The bootstrap command creates an account; it is not a password-reset command.

```bash
python3 scripts/dev.py status
python3 scripts/dev.py verify
python3 scripts/dev.py down
```

`python3 scripts/check_foundation.py` additionally checks persistence by restarting this project and briefly stopping Redis; it records sanitized memory/version/readiness measurements.

`verify` builds a separate test image and exercises real runtime-role RLS, HTTP sessions and private storage. It creates synthetic accounts/content and cleans them up. Run it after `up`. `down` preserves named volumes. Avoid `docker compose down -v` when you want to keep data. Stop the stack when it is unused to release its RAM.

The embedding service has no published host port and uses a generated private HTTP token. Only the frontend (127.0.0.1:8080) and API (127.0.0.1:8000) are published. PostgreSQL, Redis and MinIO remain on the Compose network. `/health/live` checks the API process; `/health/ready` checks PostgreSQL/migration/runtime role, Redis, private storage and the Celery worker. `retrieval_ready` reports search-service capability when core services and the embedding service are reachable. Workspace-specific active-index readiness and authorized facets are available from the search endpoint. A busy CPU producer returns an explicit retryable search error.

## Modules

- `backend/src/videomind/identity`: credentials, sessions, workspace identity.
- `backend/src/videomind/assets`: authorized source metadata.
- `backend/src/videomind/infrastructure`: database transactions, storage, telemetry.
- `backend/src/videomind/workers`: bounded Celery configuration.
- `backend/src/videomind/connectors`: upload/local-folder adapters and source routes.
- `backend/src/videomind/ingestion`: original storage, durable jobs and reconciliation.
- `backend/src/videomind/preprocessing`: isolated format probing and bounded document extraction/OCR/rendering.
- `backend/src/videomind/evidence`: authorized document pages, artifacts, immutable revision downloads and citation resolution.
- Phase 0 boundary contracts live in each owning module and `contracts.py`.
- `backend/migrations`: versioned PostgreSQL/pgvector schema and access policies.
- `frontend/src/features`: identity and source views, with shared HTTP code in `lib`.
- `infra`: pinned Docker builds, Compose services and reverse proxy.
- `scripts`: local lifecycle commands; `evaluation`: fixtures and measured reports.

The `embeddings` module owns CPU inference, durable indexing and generation lifecycle. The `retrieval` module owns authorized filters/candidates, evidence grouping, fusion, abstention and search response contracts.

## Development and trust boundary

Before committing or pushing, enable the [Git publication checks](docs/git-safety.md)
with `git config --local core.hooksPath .githooks`. Run
`python3 scripts/check_repository.py worktree` before staging new files. The hooks
check staged files, commit messages and committed history for common leaks.

The runtime PostgreSQL role is neither owner nor superuser and cannot bypass RLS. The API derives the actor from an opaque server-validated session, then sets a transaction-local actor for content queries. Database credentials and arbitrary SQL access are trusted server privileges: the custom actor setting is not an identity mechanism for untrusted SQL clients. Authentication tables are server-only and deliberately separate from content RLS.

Workspace membership plus a source grant is required for ordinary members; workspace administrators manage their workspace's sources. Provider-specific item ACLs are deferred and unsupported modes fail closed. MinIO is private, with a bucket-scoped application identity; privileged migration/storage/bootstrap credentials are confined to their one-shot jobs. Local HTTP cookies are HttpOnly/SameSite Strict. Exposing this deployment beyond loopback requires a separate TLS/deployment design.

The private embedding service loads the pinned CPU model on its first request and keeps it resident between jobs. Media jobs load the pinned English ASR model on CPU in a bounded worker subprocess, then release it when the job exits. Initial setup reuses the Phase 0 model cache or downloads the pinned public checkpoint; normal ingestion stays offline. The solo worker cannot forcibly enforce Celery's hard/soft task timeouts; format probes and document extraction use subprocess deadlines and database leases. Future long media tasks must preserve those bounds.

Host backend tools use `uv sync --project backend`; use `--group dev` for tests. The `feasibility` extra is installed only in the embedding image; API/ingestion images keep heavy inference separate. The `transcription` extra is installed for the media worker; model files mount read-only only where needed. Frontend development uses `pnpm --dir frontend install --frozen-lockfile` and `pnpm --dir frontend dev` (the Vite server proxies the local API).

See the [architecture](docs/architecture-proposal.md), [implementation plan](docs/codex-implementation-plan.md), [Phase 0 measurements](docs/phase0-feasibility.md), [Phase 1 validation](docs/phase1-validation.md) and [intake validation/datasets](docs/intake-validation.md) and [Phase 2 completion](docs/phase2-validation.md), plus [document evidence](docs/phase3-validation.md) and [media evidence](docs/phase4-validation.md), plus [embedding/index validation](docs/phase5-validation.md) and [search validation](docs/phase6-validation.md) and [evaluation findings/open release gates](docs/phase7-validation.md).

## Local backups

The recovery journal runs with Compose and retains committed deletion/reinstatement history on a separate persistent volume. Create a verified private backup with `backend/.venv/bin/python scripts/backup.py create`; inspect it with `scripts/backup.py status` using the same interpreter. `scripts/backup.py drill` restores only disposable targets. See the [recovery runbook and limits](docs/local-recovery.md). A daily Codex backup check is installed for this chat; it depends on the laptop, Docker and Codex scheduler being available. Backups remain on the same disk and do not automatically expire.

## Try the starter data

The current workspace includes **Starter dataset** (ten files) and **Local starter folder** (three files). These combine two tiny licensed public samples with generated fixtures and an attribution document. They validate uploads, original preservation, evidence and native embedding paths. The small query smoke checks do not establish broad search relevance. See [dataset research](docs/research/local-mvp-datasets.md).

To reproduce the public downloads, run `python3 scripts/fetch_starter_data.py`. After generating the Phase 0 fixtures, `python3 scripts/demo_intake.py` imports them through the authenticated API and checks byte hashes. `python3 scripts/check_intake_faults.py` tests disposable folder changes and service restart/lease recovery; it briefly restarts this project's worker and Redis.

## Planned action-search improvements

See the [action retrieval and temporal localization plan](docs/action-temporal-retrieval-plan.md) for the proposed CPU experiments, modular responsibilities and acceptance criteria. [Model options and primary sources](docs/research/action-temporal-options.md) are recorded separately. The plan starts with reviewed event intervals and calibration; it does not change the current model, relevance cutoff or index.

AT0 review preparation and AT1 offline CPU experiments are now available through `scripts/evaluate_action_temporal.py`. See [validation and commands](docs/action-temporal-validation.md) and the [human review worksheet](evaluation/annotations/action-temporal-v1-review.md). These tools preserve the live search policy and index.

The [development review pack](evaluation/reports/action-temporal-review/index.md) provides original-video links, timestamped frames and uncertain event proposals. Regenerate it offline with `backend/.venv/bin/python scripts/evaluate_action_temporal.py inspect`. Agent observations remain separate from independent human annotations.

Offline calibration now records a [no-policy decision](evaluation/manifests/action-temporal-calibration-v1-decision.json): all tested window/cutoff settings fail the provisional development gates. Run `backend/.venv/bin/python scripts/evaluate_action_temporal.py calibrate` to reproduce; see the [calibration findings](docs/action-temporal-validation.md#offline-calibration-decision). Reserved quality remains withheld.
