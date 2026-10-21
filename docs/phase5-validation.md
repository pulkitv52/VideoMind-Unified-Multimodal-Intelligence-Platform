# Phase 5: embeddings and index generations

The user authorized Phase 5 on 19 October 2026. This phase adds CPU embedding, durable indexing, generation publication and administrative diagnostics. Completion on the CPU-only laptop is recorded with final measurements and acceptance evidence in `evaluation/reports/phase5-completion.json`.

## What runs locally

One private `embedding` service loads the Phase 0 checkpoint, `google/embeddinggemma-2` revision `914f7f89142e33e77833254d9c9b90c3cef7303b`, in FP32 on CPU. Its processor and every checkpoint file have pinned hashes. The application, ingestion worker and indexer do not import Torch. Model files mount read-only; the model service receives neither database nor MinIO credentials and has no published host port. Its HTTP inference endpoint requires a generated shared token. Normal inference uses local files with Hugging Face offline mode.

The model produces normalized 768-dimensional vectors. Query text and corpus text use their distinct retrieval prompts. OCR and ASR remain text representations. Page images, timestamped video frame sequences and full-timeline native audio windows receive their own native vectors. Each stored vector references its segment, profile, canonical input hash, producer and partition bounds. Segment evidence preserves the original page, time or text locator.

Standalone PNG/JPEG files receive one native image view after sandboxed format validation. A small validation-receipt trigger publishes the existing immutable original as image evidence, with its dimensions, a full-image box and a pinned `native-image-v1` profile. It performs no parsing or object write in PostgreSQL. The existing evidence viewer displays and cites that original. This adapter does not claim OCR text.

`preprocessing` still owns extraction. `embeddings/runtime.py` owns model adaptation and measured processor-token admission; `server.py` owns the private queue; `indexer.py` owns durable jobs, verified artifact reads and publication; `generations.py` owns generation lifecycle. `repository.py` provides the authorized exact/ANN baseline. This phase's probe is an administrator diagnostic, not the Phase 6 user search product.

## Resource bounds and scheduling

The embedding service has two CPU shares, a 6.5 GiB memory ceiling and a 128 MiB temporary filesystem. It loads one model, runs one inference request at a time, and admits at most 16 waiting requests. Text query requests precede corpus requests already waiting in that queue. Running inference is non-preemptive. A 590-second watchdog exits a stuck model process; Docker restarts it and PostgreSQL jobs remain recoverable. An HTTP request is limited to 32 MiB. Text inputs are bounded to 200,000 characters, audio to 20 seconds of mono 16 kHz samples and video to 301 supplied frames. Existing preprocessing bounds continue to apply.

The adapter counts the processor's actual attention-mask tokens with text truncation disabled and predecoded video sampling disabled. Inputs above 7,500 tokens split recursively into ordered text characters, video frames or audio samples. Every input unit appears in a recorded partition. An indivisible oversized image or more than 64 partitions fails explicitly. Invalid dimensions, nonfinite values, non-unit vectors, gaps, overlaps and over-budget partitions are rejected before storage. Query text must fit one partition.

The indexer has a 256 MiB container ceiling. A shared PostgreSQL session advisory lock coordinates corpus inference, query inference and the existing CPU ingestion worker. The worker tries that lock before claiming a receipt, so waiting for inference does not hold an ingestion lease or prevent its control ping. The indexer renews its own unexpired lease while waiting or encoding. This is laptop scheduling, not a throughput or latency SLA. Model memory remains resident between jobs. The local limits are eight retained generations and 50,000 vectors per workspace, including history.

## Durable publication and changes

PostgreSQL is the indexing job authority. The indexer reconstructs work from registered active, building and standby generations; it does not require Redis deliveries. Registration records the requesting workspace administrator. Disabled or removed administrators no longer appear in the trusted scheduling inventory. Each source-scoped job has a lease token, attempt, state and manifest under forced RLS. Expired jobs can be reclaimed; stale tokens cannot publish. Failed jobs and repeatedly expired producers become terminal after three attempts and can be retried explicitly.

Targets follow the intake module's `latest_revision_id` and the newest ready segmentation for that revision. `current_revision_id` remains the published output pointer. New originals, revised desired pointers, ready segment sets and tombstones increment a workspace content epoch. Source removal and asset deletion remove generation membership immediately. Replacement preserves the previous complete membership while the new revision is processed. A newer revision or segmentation fences a worker publishing stale input.

Each complete segment's vectors commit together. A killed producer can leave complete cached vectors, but it cannot publish incomplete asset membership. On retry, the indexer validates cached partition coverage and reuses matching workspace/profile/input hashes. Object downloads check scoped metadata, size and SHA-256. Vector writes, generation membership and cutover use the storage writer lock order and a workspace change lock. The generation's asset membership changes only after all current segments have vectors. The ready receipt and membership commit together.

A generation coverage manifest reports eligible assets, published assets, unfinished extraction, partial extraction and files without ready inputs. Known extraction failures remain excluded and visible; they are not silently converted to vectors. Cutover reconciles under the workspace lock, checks complete eligible coverage and unfinished jobs, records the change watermark, then changes the active generation and publication pointers transactionally. Queries pin one generation/profile for their lifetime. New revisions feed building, active and retained standby generations. Restore rechecks coverage, so an outdated generation cannot bypass catch-up.

The current runtime can serve both default and changed text-prompt profiles for the pinned checkpoint. Their vectors and indexes stay separate. A different checkpoint, precision, processor or adapter is rejected by this deployment; it needs a separately validated runtime before migration. The lifecycle itself does not assume equal dimensions mean equal spaces.

## Indexes, access and diagnostics

PostgreSQL stores vectors with pgvector. Exact cosine search is the reference baseline. Each embedding profile receives a separate partial HNSW cosine index; a canonical profile UUID in the query fixes its compatible space. Lexical inputs retain their existing GIN index for Phase 6. No external vector database is introduced.

The baseline joins generation membership, assets, source-scoped vectors and citations under the runtime role. A materialized candidate query keeps its authorized membership predicate correlated, allowing the ordered HNSW scan. The runtime-role EXPLAIN check verifies the physical index is used. ANN uses iterative scanning and bounded search effort, with exact fallback when it returns too few visible candidates. Access filters remain mandatory. Per-workspace active pointers do not authorize access to another source. Current RLS and source grants apply after generation pinning, including revocation in an existing session. Sparse-filter recall and large-corpus ANN tuning remain evaluation work.

Workspace administrators can start a generation, inspect coverage, retry failed jobs, activate a complete generation and restore a caught-up previous generation. Members see no private-source coverage counts. File lists report embedding status under the same source authorization as originals. `POST /api/workspaces/{w}/indexes/probe` embeds a bounded text query and returns vector neighbors with citations for validation. It has no answer generation, hybrid ranking or user search UI. `retrieval_ready` remains false until Phase 6.

## Validation and reproduction

Run `python3 scripts/dev.py up` and `python3 scripts/dev.py verify`. Setup preserves credentials, object volumes and model caches. `scripts/prepare_embedding.py` checks the pinned Phase 0 cache against `evaluation/manifests/embedding-files.json` and materializes its files under `.local/models/embedding`. Existing verified files are reused; missing files download from the exact public revision. Downloads are checked before atomic replacement, using bounded buffers. Initial setup needs disk space for the pinned checkpoint.

The acceptance report separates deterministic vector/lifecycle fault tests from real model/corpus measurements. Fault checks include a producer killed with SIGKILL after vector commit, lease reclaim, duplicate publication, invalid vectors, replacement, deletion, source-grant revocation, exact/ANN comparisons and profile cutover/rollback. The private service tests exercise authentication, profile mismatch, request limits and query queue priority with a lightweight test adapter. Real corpus checks validate the pinned model across text, page images, video and native audio, provenance and original preservation.

The demo pack and synthetic queries establish working paths. They do not establish broad semantic accuracy, ASR accuracy, representative throughput or filtered ANN recall at scale. GPU execution, specialized modality indexes and multiple heavy production workers remain deferred. Retained vectors and old generations consume database storage; automatic generation retirement is not implemented in this local phase.

## Release tests

The final deployed suite passed **157 tests in 146.27 seconds**. Two additional checkpoint-preparation tests passed in 0.03 seconds. Strict TypeScript and the frontend production build passed. The final suite includes a concurrent source-removal/cutover test: mutations wait for the publication lock, then remove membership without deadlock or stale exposure. Generation profile/initiator identity is immutable, and repeated producer crashes terminate after three expired attempts. Every application table has forced RLS; the runtime role owns none of them and cannot bypass RLS.

## Retained corpus results

The active generation contains all 46 retained assets and 197 provenance-linked vectors: 90 text, three OCR, 16 image, 81 video, five native audio and two transcript vectors. Four synthetic/public smoke queries found the expected safety, moving-square, beep and cat-image evidence in their exact top 10. HNSW returned the same top-10 vector IDs on those queries. All five source-filter checks stayed within the requested source. These are small-corpus checks, not a representative relevance or filtered-recall benchmark.

Every original passed SHA-256 verification. All 80 citations returned by the eight query runs resolved to the correct retained revisions. The retained document checker separately verified eight documents and 107 citations; the media checker verified 36 files, 88 citations and all 17,183 decoded video frame mappings at rounded-millisecond resolution. The two standalone images add their own native citations. Runtime checks found no vector without a citation. Vector norms ranged from 0.999999872 to 1.000000165; the largest actual processor input used 1,586 tokens. The service rejected an oversized real query instead of truncating it and encoded two distinct prompt profiles against the pinned model.

The browser confirmed activation at 46/46, per-file Indexed status, original-image display and stable image-citation restoration. `evaluation/reports/phase5-index.jpg` and `phase5-image-evidence.jpg` record those views. Full release test counts, runtime versions, resource snapshots and source hashes are in the completion report. One upstream Starlette/httpx TestClient deprecation warning remains.

The nine running services used about 4.81 GiB in one post-verification snapshot with the model loaded; the embedding process accounted for about 4.13 GiB. This is an idle snapshot, not inference peak memory. No GPU was used. Corpus probe timings include cold start and concurrent validation work and are recorded as observations rather than a latency benchmark.
