# Phased Codex implementation tasks

Status: Phases 0 and 1 passed their local CPU checks on 18 October 2026. GPU execution remains unverified. Phase 2 completion was authorized on 19 October 2026. Its final validation is recorded in [phase2-validation.md](phase2-validation.md); Phase 3 was completed and validated on 19 October 2026. Phase 4 completed local CPU validation on 19 October 2026; Phase 5 completed CPU validation on 20 October 2026; Phase 6 completed CPU validation on 20 October 2026; Phase 7 local evaluation was authorized on 20 October 2026; measured failures and missing release evidence keep its gate open. See the [feasibility report](phase0-feasibility.md) and [foundation validation](phase1-validation.md) for measurements and limits.

The user has selected the existing CPU-only laptop as the MVP target. GPU work and scaling benchmarks are deferred. Keep one loaded embedding service and bound heavy-job concurrency. Phase 1 measured the six-service stack at 244.48 MiB in one idle snapshot; combined inference-plus-stack peak memory remains unmeasured.

Read the architecture proposal for requirement IDs, schema definitions, invariants and benchmark targets. Keep those values in versioned configuration when implementing them.

## Phase 0: Check feasibility and define contracts

Dependencies: design approval and an implementation request.

Task: Validate the exact `google/embeddinggemma-2` checkpoint and processor on target CPU hardware. GPU validation is deferred. Exercise text, scanned-page image, silent video frames and native audio, including speechless sound. Determine whether the chosen runtime handles video soundtracks; baseline uses explicit separate tracks. Measure token counts, memory, warm query latency and representative batch throughput. Pin model/runtime revisions, OCR/ASR models, FFmpeg and document rendering dependencies. Validate their packaging and licenses. Define Pydantic connector envelopes, typed locators, embedding profiles, publication manifests and search/evidence response contracts. Record adopted decisions in short ADRs.

Exit: reproducible smoke report contains finite normalized 768d vectors for every required modality; shared-space similarity sanity cases pass; media budget overflow splits rather than truncates; CPU resource measurements exist; GPU work is deferred; unresolved blockers and supported hardware are explicit. No placeholder/fake embedder qualifies as model validation.

## Phase 1: Local infrastructure, identity and persistence

Completed locally on 18 October 2026: 54 tests passed, fresh migrations passed, browser sign-in/sign-out passed, restart persistence and Redis-failure readiness passed. Actual PostgreSQL 16.15 and pgvector 0.8.7. See [validation and limitations](phase1-validation.md).

Dependencies: Phase 0 contracts.

Task: Scaffold uv/FastAPI and pnpm/Vite/React projects, Compose services and health checks. Follow the proposed modular folder structure in the architecture document, creating module directories when they gain implementation. Create Alembic migrations for workspaces/access, assets/revisions/objects, processing/outbox, segment/evidence and embedding/generation metadata. Use a local bootstrap identity flow with multiple test users; no authentication bypass in content endpoints. Configure private MinIO and runtime DB roles/RLS. Add structured logs, trace propagation and resource limits.

Exit: documented setup boots on a fresh supported host; readiness reflects dependencies; migrations upgrade from empty DB; fixtures demonstrate workspace/source isolation using the runtime role; secrets are absent from source; persistent volumes survive restart. Confirm actual database and pgvector versions in the lock/report.

## Phase 2: Connectors and durable ingestion

Completed on the local CPU stack on 19 October 2026. The intake milestone is extended with protocol adapters, revision-checked paged discovery/fetch, durable completed cursors/progress, storage reservations/quotas, orphan and retention cleanup, file/job pagination and process-kill verification. The full runtime-role suite passed 82 tests; strict TypeScript and production frontend build passed. See [Phase 2 validation and limits](phase2-validation.md).

Dependencies: Phase 1.

Task: Implement upload and allowlisted read-only folder connectors against one contract. Add byte/MIME/size validation, immutable storage, change detection, tombstones, PostgreSQL job stages, outbox dispatcher, Celery scheduling, fenced leases and reconciliation. Implement user-facing job status/error/retry contracts. Bound retries and temporary storage.

Exit: unchanged sync is a no-op; changed bytes create a new immutable revision; malicious paths/symlinks and oversized inputs are rejected; worker death, duplicate delivery and Redis loss converge without duplicate published work; a tombstoned source cannot be republished by an old task. Source progress survives restarts.

## Phase 3: Document ingestion and evidence viewing

Completed on the local CPU stack on 19 October 2026: 105 tests passed, strict TypeScript and production frontend build passed, and the browser verified PDF/OCR, DOCX and text evidence. All 46 existing originals and 107 document citations were verified. Adopted limits and behavior are recorded in [Phase 3 validation](phase3-validation.md).

Dependencies: Phase 2.

Task: Add PDF/DOCX/TXT/Markdown extraction, scanned/mixed-page OCR, layout-aware chunking, PDF page/tile image representations and stored coordinate/text mappings. Produce pinned DOCX-to-PDF derivatives. Add a minimal UI to upload, see progress, inspect extracted pages/spans and resolve citations. Keep extraction output distinguishable from original content.

Exit: section/table/multipage fixtures preserve evidence mapping; OCR-only pages are searchable inputs; every document segment resolves to the proper original revision/page/region or structural text anchor; corrupt/encrypted/render-failed cases show actionable status; parser limits are exercised.

## Phase 4: Video and audio ingestion and playback

Completed locally on 19 October 2026: 134 tests passed, frontend checks passed, all 36 existing media files processed, and 88 media citations plus frame mappings were verified. See [media validation](phase4-validation.md) for bounds, measurements and limitations.

Dependencies: Phase 2 and the locator contracts. This phase can follow the document work.

Task: Add track probing, original PTS preservation, shot/window segmentation, explicit visual frame sampling, audio extraction/resampling, full-timeline native audio windows and timestamped local ASR. Build previews and supported-codec playback derivatives with mapping manifests. Add authenticated HTTP Range playback and UI seeking/highlighting.

Exit: silent video, spoken video and standalone audio each produce valid evidence; non-speech audio survives VAD; variable-frame-rate/nonzero-PTS fixtures preserve alignment; all playback fixtures meet the proposal's seek tolerance; unsupported codecs use an explicitly mapped derivative. Access revocation denies subsequent media requests.

## Phase 5: Embedding lifecycle and atomic publication

Completed locally on 20 October 2026: 157 release tests and two checkpoint preparation tests passed. All 46 retained assets have 197 provenance-linked vectors in an active generation. Native-image evidence, real-model smoke queries and actual HNSW index use were verified. See [embedding/index validation](phase5-validation.md) and its acceptance report for the tested scope and limits.

Dependencies: Phases 0, 3 and 4.

Task: Implement resource-bounded shared embedding service, query priority, modality adapters and profile/input hashing. Embed native media plus extracted text separately. Add vector validation, exact cosine baseline, profile-isolated HNSW indexing and generation membership publication. Implement incremental backfill, dual generation ingestion, watermark catch-up, atomic cutover and rollback.

Exit: all four source classes have provenance-linked vectors; invalid outputs and budget violations are rejected; queries pin one generation; partial/error branches are visible; concurrent revision update, deletion and model migration preserve current membership; old/new profile vectors never mix. Coverage manifests and rollback checks pass.

## Phase 6: Authorized hybrid search and usable evidence UI

Completed locally on 20 October 2026: 188 release tests and the frontend build passed. Real-model checks preserved all 46 originals, verified 64 citation resolutions and 34 viewer descriptors, found the expected fixtures in both dense candidate strategies and rejected six development negatives. Exact cosine is the adopted local search baseline; ANN scale gates and broad relevance evaluation remain Phase 7. See [search validation and limits](phase6-validation.md).

Dependencies: Phase 5.

Task: Implement authorized dense and PostgreSQL FTS candidates, identifier lookup, evidence-group RRF, exact rescoring and source diversity. Add filter semantics, bounded neighboring evidence, stable citations and relevance-based abstention. Build a search UI with meaningful filters, match provenance, document viewer, media player and job warnings. Add per-modality candidate retrieval as an experiment configuration.

Exit: F1–F9 work end to end against fixtures; candidate/group duplicates do not multiply rank votes; facets/caches/neighbor expansion cannot leak restricted data; native silent-video and non-speech audio queries succeed without generated captions; every top result opens its evidence. Text-only reranking cannot suppress all nontext results.

## Phase 7: Evaluation, resilience and MVP release gate

Local diagnostic tooling, a provisional frozen corpus, video sampling experiments and an isolated restore drill are implemented. Denser sampling did not resolve fighting retrieval. These measurements do not satisfy the original gold-set, relevance, latency and operational release criteria. See [Phase 7 evidence and open gates](phase7-validation.md).

Dependencies: Phase 6; annotation preparation may begin after Phase 0.

Task: Freeze licensed gold manifests and qrels, adjudicate labels, build reproducible quality/performance runs, compare baselines and index strategies, and record all metrics by modality. Run ACL, restart, deletion, backup/restore and migration fault suites. Document resource envelopes, setup/run/recovery procedures and unresolved limitations.

Exit: every section 9 release gate is measured and met, or an explicit user-approved scope/hardware revision is recorded before declaring MVP complete. Reports cover the local laptop scope, including cold/warm and concurrent-ingestion results; large-corpus, multi-client and GPU scaling benchmarks are deferred; synthetic vector load is labelled separately from real content. Restore reproduces originals, active generation and citations; deleted assets remain unavailable after restoration and tombstone replay.

## Action and temporal retrieval follow-up (proposed)

The user requested a documented plan on 20 October 2026. [The action/temporal plan](action-temporal-retrieval-plan.md) defines AT0–AT5 within Phase 7: review labels and freeze splits, test acceptance and window recipes, conditionally evaluate an auxiliary action branch, calibrate and assess held-out intervals, integrate only a measured winner, then rerun the release assessment. The user subsequently requested implementation: AT0 review preparation and AT1 exploratory CPU runs are documented in [action-temporal-validation.md](action-temporal-validation.md). All three native window recipes completed the bounded pilot; 21 evaluation tests and original-preservation checks passed. No setting met the development proxy gates for every phrase. Human adjudication and promotion gates remain open. [Primary-source model options](research/action-temporal-options.md) are research, not adopted dependencies. The existing 0.70 policy, model and index remain unchanged.

A subsequent development inspection adds timestamped review aids for 15 clips and preliminary AT3 overlap diagnostics against uncertain agent proposals. The review pack and limitations are linked in the validation report. The evaluation suite now passes 25 tests. This does not complete human adjudication or select a serving policy; reserved sequences remain outside development inspection.

## Product and UX follow-up (planned)

Product direction was revised on 26 October 2026: the
[self-service product plan](self-service-product-plan.md) defines S1–S6 for
self-signup, member-owned upload collections, automatic preparation and
owner/admin analytics showing joins, uploaders and indexing states. It supersedes
invitation-first onboarding and administrator-only upload-collection creation.
S1–S6 are implemented and validated for the local deployment; see
[self-service validation](self-service-validation.md) for current measured results.
Earlier validation results remain historical.

The user also requested a complete owner/admin/member management plan on
21 October 2026. See [users, roles and workspace management](users-roles-plan.md)
for the proposed A1–A7 implementation sequence, permission matrix, invitation-first
onboarding, collection grants and validation gates. This is a separate planned
extension to account/access management. Implementation was authorized on
26 October 2026, starting with A1; see [access validation](access-validation.md).
The existing Phase 7 gates remain unchanged.

The subsequent request for an admin, two members and thoroughly tested role
dashboards authorizes persistent operator-provisioned test accounts, isolated
synthetic collections, role/access summaries and a read-only People directory.
See [role dashboard validation](role-dashboards-validation.md). This is a narrow
read-only part of A3 plus the requested operator setup, not completion of A2–A7
or authorization to expose unfinished invitation/role-editing controls.

On 21 October 2026, the user requested a documented product-level UI/UX plan. The [product and UX plan](product-ux-plan.md) defines UX0–UX6: specify layouts/contracts and baseline; introduce navigation and visual foundations; improve Search and evidence inspection; add authorised result previews; improve Library and first use; clarify Settings and operational states; then validate and update documentation. Dependencies, API boundaries and per-step exits are recorded in that plan. The [UX validation checklist](product-ux-validation.md) records the first-milestone results and pending checks.

The user subsequently authorised starting implementation. Implementation began on 21 October 2026 with UX0–UX2; later UX steps remain pending. The first milestone now has a passing frontend build, 24 desktop/mobile browser checks and 199 running-stack tests; see the UX validation record for coverage and limitations. The work extends Phase 6 presentation while preserving the contracts/invariants from Phases 2–6; it does not restart deferred action-retrieval experiments or waive any Phase 7 gate. Before implementing each step, read the relevant phase validation and acceptance reports. Existing text/image query support must be preserved; audio/video query uploads remain future work.

## Later work

- Provider connectors: define incremental-sync and item-ACL/revocation guarantees per provider, then pass the connector contract and isolation tests.
- Additional multimodal queries: the current frontend/API already support bounded still-image queries; retain that support. Audio/video query uploads and broader query-to-corpus evaluation remain later work.
- Generated answers: select a separate generator, add claim-level citation validation, prompt-injection resistance and groundedness/abstention evaluation.
- GPU and scale: defer GPU runtime support, larger-corpus/multi-client benchmarks, partitions, physical index splitting and specialized models until the local MVP works and a measured bottleneck justifies them.

For each implementation request, deliver the code changes, verification results and updated decisions. Use the repository's commit format when a commit is requested. Deployment, external connector account setup and generator selection each need a separate request.

The subsequent offline calibration evaluated all 12 native/control/window and cutoff combinations against provisional development event ranges. None met every asset, ADL-admission and conservative localization gate for every fall paraphrase. The frozen decision selects no policy, reserved quality remains unevaluated and the suite passes 28 tests. The user subsequently deferred further action/temporal work because current search meets their immediate needs. AT2 and AT4 remain unstarted; resume this work only on a new request. See [calibration evidence](action-temporal-validation.md#offline-calibration-decision).

## Local recovery follow-up

The user authorized backup/recovery reliability work after deferring action/temporal experiments. This adds an operator-only transactional change journal with independent persistent export, coordinated snapshot-bound backup commands, saved/latest journal replay in disposable restores, a daily Codex backup check and a local recovery runbook. See [local-recovery.md](local-recovery.md) for validation and remaining limits. This is operational progress within Phase 7; it does not waive the original quality, performance, independent-review or incident-recovery criteria. Additional audio/video query inputs remain later work; existing image-query support is preserved.
