# Developer guide

For installation and everyday use, start with the [README](../README.md). This guide covers the implementation, local service behavior and research tools.

The [product and UX plan](product-ux-plan.md) describes the proposed interface work, implementation sequence and scope boundaries. Its [validation record](product-ux-validation.md) records the implemented UX0–UX2 milestone and the pending acceptance checks for later work.

## Local services and verification

The header's **Light theme / Dark theme** button changes the appearance across
Search, Library, Settings and evidence views. It is also available on sign-in.
On first use, the app follows the browser's light/dark preference. An explicit
choice is saved in this browser under `videomind-theme`; if browser storage is
blocked, switching still works until the page reloads. Original document pages
and media retain their source colors.

Theme validation (21 October 2026): `make build-frontend` passed and
`make test-frontend` passed all 28 desktop/mobile browser checks, including
system preference, persistence after reload, blocked storage, sign-in switching
and 320px reflow. The browser suite uses synthetic API fixtures; it does not
measure retrieval quality or establish full accessibility compliance.

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

Before committing or pushing, enable the [Git publication checks](git-safety.md)
with `git config --local core.hooksPath .githooks`. Run
`python3 scripts/check_repository.py worktree` before staging new files. The hooks
check staged files, commit messages and committed history for common leaks.

The runtime PostgreSQL role is neither owner nor superuser and cannot bypass RLS. The API derives the actor from an opaque server-validated session, then sets a transaction-local actor for content queries. Database credentials and arbitrary SQL access are trusted server privileges: the custom actor setting is not an identity mechanism for untrusted SQL clients. Authentication tables are server-only and deliberately separate from content RLS.

Workspace membership plus a source grant is required for ordinary members; workspace administrators manage their workspace's sources. Provider-specific item ACLs are deferred and unsupported modes fail closed. MinIO is private, with a bucket-scoped application identity; privileged migration/storage/bootstrap credentials are confined to their one-shot jobs. Local HTTP cookies are HttpOnly/SameSite Strict. Exposing this deployment beyond loopback requires a separate TLS/deployment design.

The private embedding service loads the pinned CPU model on its first request and keeps it resident between jobs. Media jobs load the pinned English ASR model on CPU in a bounded worker subprocess, then release it when the job exits. Initial setup reuses the Phase 0 model cache or downloads the pinned public checkpoint; normal ingestion stays offline. The solo worker cannot forcibly enforce Celery's hard/soft task timeouts; format probes and document extraction use subprocess deadlines and database leases. Future long media tasks must preserve those bounds.

Host backend tools use `uv sync --project backend`; use `--group dev` for tests. The `feasibility` extra is installed only in the embedding image; API/ingestion images keep heavy inference separate. The `transcription` extra is installed for the media worker; model files mount read-only only where needed. Frontend development uses `pnpm --dir frontend install --frozen-lockfile` and `pnpm --dir frontend dev` (the Vite server proxies the local API).

See the [architecture](architecture-proposal.md), [implementation plan](codex-implementation-plan.md), [Phase 0 measurements](phase0-feasibility.md), [Phase 1 validation](phase1-validation.md) and [intake validation/datasets](intake-validation.md) and [Phase 2 completion](phase2-validation.md), plus [document evidence](phase3-validation.md) and [media evidence](phase4-validation.md), plus [embedding/index validation](phase5-validation.md) and [search validation](phase6-validation.md) and [evaluation findings/open release gates](phase7-validation.md).

## Starter data and fault checks

Public sample downloads and their licences are described in [dataset research](research/local-mvp-datasets.md). Run `python3 scripts/fetch_starter_data.py` to download them. After generating the Phase 0 fixtures, `python3 scripts/demo_intake.py` imports them through the authenticated API and checks byte hashes.

`python3 scripts/check_intake_faults.py` checks disposable folder changes and service restart/lease recovery. It briefly restarts this project's worker and Redis.

## Backup operations

See the [recovery runbook](local-recovery.md) for backup verification, disposable restore drills, deletion history and operator recovery procedures. Scheduler configuration belongs to the local installation; cloning this repository does not install a backup schedule.

## Planned action-search improvements

See the [action retrieval and temporal localization plan](action-temporal-retrieval-plan.md) for the proposed CPU experiments, modular responsibilities and acceptance criteria. [Model options and primary sources](research/action-temporal-options.md) are recorded separately. The plan starts with reviewed event intervals and calibration; it does not change the current model, relevance cutoff or index.

AT0 review preparation and AT1 offline CPU experiments are now available through `scripts/evaluate_action_temporal.py`. See [validation and commands](action-temporal-validation.md) and the [human review worksheet](../evaluation/annotations/action-temporal-v1-review.md). These tools preserve the live search policy and index.

The [development review pack](../evaluation/reports/action-temporal-review/index.md) provides original-video links, timestamped frames and uncertain event proposals. Regenerate it offline with `backend/.venv/bin/python scripts/evaluate_action_temporal.py inspect`. Agent observations remain separate from independent human annotations.

Offline calibration now records a [no-policy decision](../evaluation/manifests/action-temporal-calibration-v1-decision.json): all tested window/cutoff settings fail the provisional development gates. Run `backend/.venv/bin/python scripts/evaluate_action_temporal.py calibrate` to reproduce; see the [calibration findings](action-temporal-validation.md#offline-calibration-decision). Reserved quality remains withheld.

## Frontend UI checks

The first product milestone uses pinned Playwright 1.62.1 and the installed Google Chrome browser. Run `pnpm --dir frontend test:ui` for isolated synthetic desktop/mobile journeys; it starts a separate loopback Vite server on port 4174. These fixtures do not contact the live application APIs. Captures stay under ignored `.local/ux-browser-tests`. Run real-model browser checks separately from `scripts/dev.py verify`, since both real search and ingestion share the CPU gate.
