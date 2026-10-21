# Phase 4: media processing and playback

The user authorized Phase 4 on 19 October 2026. The complete deployed suite passed **134 tests in 142.50 seconds**. Strict TypeScript and the frontend production build passed. The phase runs on the existing CPU-only laptop.

## What users can do

Choose **Open media** beside a processed video or audio file. The player opens a browser-compatible copy. Visual windows include sampled frames; native audio windows retain speech, music, silence and other sounds. Local ASR provides separately labelled transcripts when it detects speech. Clicking evidence seeks to its interval; clicking a transcript word seeks to its timestamp and highlights the active word.

A stable media citation restores the original revision, segment set and interval. Original downloads retain the exact imported bytes. Replacing a file keeps earlier citations usable while the original asset remains accessible. Revocation or disconnection denies the next metadata, image, citation or playback request, including subsequent byte ranges. Bytes already delivered remain with the client.

Search inputs are prepared, but embedding and semantic search remain Phases 5–6. The app continues to return `retrieval_ready=false`.

## Module boundaries and storage

`preprocessing/media` owns the immutable producer profile, sandboxed decoder/ASR, validated output contract and atomic publication. `evidence/media_routes.py` owns authorized descriptors, timeline listings and HTTP Range responses. The frontend media viewer and citation router are separate from the document viewer. Shared job fences live in `ingestion/jobs.py`; the Linux parser sandbox is shared under `preprocessing/sandbox.py`.

Two new source-scoped tables have forced RLS and immutable runtime metadata. `media_presentations` binds a ready segment set to playback and mapping objects. `media_artifacts` records every derived object, including sampled frames and mapping manifests, so retention cannot reclaim a live artifact. Segments use typed temporal anchors and opaque citations. Transcript text also populates lexical input rows.

New and existing format-validated media receive durable PostgreSQL receipts and outbox events. Publication reserves quota before storage writes, then checks the current lease, principal, source and asset before committing objects, segments, citations, mapping references and ready status together. A stale lease, quota failure or killed writer cannot expose partial evidence. Interrupted writes remain charged until confirmed cleanup. Media derivatives use the existing one-hour retention floor and shared/exclusive storage lock.

Optional ASR failure leaves native evidence and playback available. The processing run and stage report `partial`, with the failed branch visible in the manifest and UI. Retrying builds another complete media segment set atomically. Old citations keep their original set and artifacts; history continues to count against the workspace quota. Essential decode or playback-mapping failures publish no set and show an actionable error.

## Original time and derived inputs

PyAV records each decoded video frame's exact integer PTS and rational time base. Comparing those exact values preserves distinct frames less than one millisecond apart. Citation boundaries use rounded original milliseconds; the exact timestamps remain in the mapping. Native audio metadata retains frame PTS, sample rate, sample count, track index and channel count.

The common origin is the earliest supported decoded track timestamp. Playback time zero maps to that original origin. Canonical mono 16 kHz PCM audio uses explicit timestamp resampling and leading silence to preserve track offsets. Native audio windows cover the full canonical timeline, including intervals VAD omits. ASR uses VAD and word timestamps on that canonical track; its timestamps map back through the recorded origin.

Video inputs produce approximately one sampled JPEG per second. A frame-difference heuristic proposes shot boundaries, separated by at least two seconds. Visual windows are at most 12 seconds, with two-second overlap inside longer shots. Each visual input manifest identifies its source frames and exact timestamps; evidence transforms include the stored frame object IDs. Audio uses 20-second windows with two-second overlap, each stored as PCM WAV. These native inputs stay separate from ASR text.

Playback uses H.264/AAC MP4 for video and canonical WAV for standalone/alternate audio. Even an already playable original receives a mapped copy, which keeps codec and seeking behavior consistent. After encoding, the worker decodes the playback video's PTS again. It requires equal frame counts and at most 50 ms timestamp difference after subtracting the original origin. Unsupported or ambiguous timelines fail explicitly rather than silently flattening timing.

GET and HEAD playback requests reauthorize access and support a single byte range, open-ended ranges, suffix ranges, strong ETags and If-Range fallback. Unsatisfiable or multiple ranges return 416. The private MinIO bucket never supplies a public capability URL.

## Adopted laptop bounds

Originals retain the 64 MiB upload cap. Media processing supports at most five minutes, one video track and two audio tracks. It rejects frames above 16 million pixels, more than 36,000 decoded frames per track, unsupported negative/non-monotonic presentation timelines, and oversized manifests or outputs. The parent validates track bounds, exact PTS conversion, interval/word bounds, artifact paths and playback mappings before publication. Aggregate derivatives, including mappings, are capped at 128 MiB per media item.

The solo worker runs one heavy production job at a time, with one CPU, a 3 GiB container limit and a private 512 MiB scratch tmpfs. The media parser has a ten-minute wall deadline, a 600-second per-process CPU limit, 4 GiB address-space ceiling and 128 MiB per-file output cap. Per-command decoder/transcoder deadlines also apply. Limits are admission and containment bounds, not a promise that every five-minute, high-resolution file finishes within the deadline.

Media parsing inherits the Phase 3 Landlock/seccomp sandbox with read-only access to its ASR checkpoint. The child receives no service credentials and cannot create Internet sockets or read the parent's environment. The parent kills the parser process group on timeout or cancellation and renews only a still-valid lease while receiving progress. Required sandbox support fails closed.

The shared worker's health check accepts a fresh fenced processing heartbeat when a busy solo worker cannot answer a control ping. Intake and documents receive higher Redis delivery priority than media. Media redelivery is throttled to once per minute in reconstructible dispatcher memory; PostgreSQL remains authoritative. Restarting the dispatcher loses only that throttle and can safely duplicate delivery. Long running jobs remain non-preemptive; a new upload may wait for the current job to finish.

## Reproducible local ASR

The profile pins PyAV 16.1.0, faster-whisper 1.2.1, CTranslate2 4.8.3, English int8 inference and the `Systran/faster-whisper-small.en` revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. Model, config, tokenizer and vocabulary SHA-256 hashes are checked against fixed values. The Python lockfile and dated Debian package snapshot pin the runtime and CLI FFmpeg build.

`python3 scripts/dev.py up` prepares the checkpoint under `.local/models/asr`, reusing the Phase 0 cache when present and downloading only the pinned public files otherwise. Only worker/verification containers mount that directory read-only. Normal ingestion is offline. The ASR model loads in the job subprocess and exits with it. The embedding model remains unloaded. Package notices stay in the image; model/runtime hashes are recorded in the acceptance report.

## Measured evidence

The 134-test suite covers the previous phases plus real CPU ASR, non-speech retention, silent/spoken video, unsupported original codec conversion, VFR and nonzero PTS, sub-millisecond frame spacing, A/V offset silence, corrupt media, duration/deadline bounds and checkpoint identity. Runtime-role integration tests cover Range/HEAD/If-Range behavior, source-grant revocation in existing sessions, guessed objects, replacement, stale leases, quota rejection, a real SIGKILL after derivative PUT, reservation cleanup and media retention. A partial-branch retry preserves old citations while selecting a new complete set. One upstream Starlette/httpx TestClient deprecation warning remains.

All **46 existing originals** passed authenticated checksum verification. All **36 existing media files** are ready, with **81 native video windows, five native audio windows and two transcript segments**. All **88 media citations** resolved to the correct revision and set. Every native audio track's windows covered its full canonical timeline. All **17,183 decoded video frames** retained the same rounded-millisecond presentation mapping in playback, with a measured maximum error of **0 ms at that resolution**. This is not a sub-millisecond precision claim.

Browser checks selected a CCTV interval at 10 seconds and restored it through its citation. A disposable VFR fixture starting at original time 5 seconds sought original 15 seconds at playback time 10 seconds. Selecting the speech fixture's word "power" sought 0.680 seconds. These checks were within the 500 ms clock-seek tolerance; semantic localization accuracy is a separate future evaluation. The disposable source was disconnected afterward. Browser screenshots and raw corpus results are linked in `evaluation/reports/phase4-completion.json`.

No retrieval, ASR accuracy, shot-detection quality or representative throughput benchmark is claimed. English synthetic speech and the small demo pack establish working paths. Accents, noisy speech, diarization, multilingual transcription and arbitrary edit lists still need broader evaluation. Sparse frame sampling can miss short events, and frame-difference cuts do not identify semantic actions. Other operating systems, GPU execution and concurrent heavy production processing remain unverified.

## Repeating the checks

Run `python3 scripts/dev.py up`, then `python3 scripts/dev.py verify`. Run `backend/.venv/bin/python scripts/check_media_evidence.py` to verify existing demo originals, ranges, mappings, full-timeline audio coverage and media citations. Run the document checker too when changing shared evidence or sandbox code. These checkers read the generated owner credentials without printing them. Preserve `.env`, `.local` and named volumes.
