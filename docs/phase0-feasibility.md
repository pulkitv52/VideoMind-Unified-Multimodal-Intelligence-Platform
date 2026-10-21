# Phase 0 feasibility report

Updated: 18 October 2026. Status: CPU feasibility checks passed. GPU support remains unverified.

The pinned model now produces finite, normalized 768-dimensional embeddings for text, scanned pages, silent video, speech, non-speech sound, and the separately decoded visual/audio tracks of spoken video. All native views passed the matching-description sanity check. A small unified dense retrieval check also passed. Local OCR, timestamped ASR and DOCX-to-PDF conversion passed their fixture checks.

The user has confirmed CPU-only laptop development as the MVP scope; GPU acceleration and scaling are deferred. This closes the local CPU feasibility work. It does not establish production readiness or the Phase 7 retrieval and performance targets. Later phases remain subject to a user request.

## What was delivered

- Modular Pydantic contracts for connectors, segments, evidence locators, embedding profiles, publication manifests, search and viewers.
- A pinned CPU runtime, model revisions, synthetic fixtures and offline evaluation runners with source/profile/fixture hashes.
- Token-budget splitting that retains every input frame, plus memory admission checks before model loading.
- Measurements from separate vision/audio configurations and the complete multimodal model.
- A working project-local document renderer and regression tests for startup and conversion.

The complete suite passed **27 tests** with local Unix socket IPC allowed. In the restrictive tool sandbox, 26 pass and the conversion test skips with a specific IPC reason. These checks cover domain consistency and feasibility; database authorization and API enforcement are still future work.

## Hardware and runtime

The test host has an AMD Ryzen 7 7730U, 8 physical cores/16 logical CPUs and about 14.96 GiB RAM. The final model run used four CPU threads and FP32 inference. Available RAM at model admission was 6.73 GiB, above the unchanged 6 GiB admission limit. GPU probing reported CUDA unavailable in the current CPU-only environment.

| Component | Pin or observed build |
|---|---|
| Python | 3.12.3 |
| Embedding model and processor | `google/embeddinggemma-2`, revision `914f7f89142e33e77833254d9c9b90c3cef7303b` |
| PyTorch / Torchvision | 2.14.1+cpu / 0.29.1+cpu |
| Transformers / Sentence Transformers | 5.20.0 / 6.1.0 |
| Hugging Face Hub / Pydantic | 1.33.0 / 2.14.1 |
| PyAV / linked FFmpeg | 16.1.0 / 8.0.1 |
| ASR | faster-whisper 1.2.1, CTranslate2 4.8.3, CPU INT8 |
| ASR checkpoint | `Systran/faster-whisper-small.en`, revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f` |
| OCR | Tesseract 5.3.4, Leptonica 1.82.0; English data and package hashes recorded |
| Renderer | LibreOffice 24.2.7.2; Ubuntu package revision `4:24.2.7-0ubuntu0.24.04.7` |
| Render font | DejaVu Sans; actual font checksum and embedded PDF font recorded |

`backend/uv.lock` records dependency versions and artifact hashes. Binary packages were extracted into the project cache. Host package installations were left unchanged.

## Measured CPU results

These are smoke measurements on tiny synthetic inputs on a shared host. Native media uses batch size one; text uses a two-item batch. The first call for each input is timed. Larger batches, long recordings, concurrent clients and end-to-end search need separate benchmarks.

| Check | Observed result |
|---|---|
| Full-model initialization | 3.691 s with cached weights |
| Warm text query, median of three | 133.70 ms |
| Two-item text batch | 0.189 s; 10.58 short passages/s |
| Relevant text / distractor cosine | 0.783 / 0.539 |
| Peak process RSS | 4,856,896 KiB, about 4.63 GiB; includes preprocessing and loading |

| Native input | Encode time | Batch-one throughput | Matching / unrelated description cosine |
|---|---|---|---|
| scanned_page | 9.973 s | 0.100 inputs/s | 0.731 / 0.516 |
| spoken_video_visual | 19.352 s | 0.052 inputs/s | 0.809 / 0.585 |
| silent_video | 19.471 s | 0.051 inputs/s | 0.809 / 0.585 |
| speech | 0.677 s | 1.477 inputs/s | 0.795 / 0.500 |
| beeps | 0.746 s | 1.341 inputs/s | 0.725 / 0.565 |
| spoken_video_audio | 0.665 s | 1.503 inputs/s | 0.809 / 0.474 |

The four-frame video inputs took about 19 seconds each on this CPU. Local operation is feasible, but visual ingestion is slow. Audio encoding was faster than the short fixture's duration. Do not extrapolate these numbers to long recordings or production workloads.

### Unified retrieval

Eight vectors shared one candidate pool: two text passages, a scanned page, two visual video views, speech, beeps and the decoded spoken-video soundtrack. Three text queries ranked every candidate by cosine:

- The safety query placed the spoken-video soundtrack, standalone speech, document and scanned page in the first four positions.
- The visual query placed the two relevant video views first.
- The sound query placed the beep recording first.

Every query's top result was relevant. This is a small dense-only sanity check. It does not measure hybrid search, access filters, abstention, broad accuracy or score calibration.

### Preprocessing and evidence preparation

The processor accepted the document, scanned page, visual frames, speech and beep waveforms. A deliberately oversized 60-frame input expanded to 7,682 tokens. It split into two 30-frame inputs of 3,842 tokens each, retaining all frames within the 7,500-token payload budget.

The checkpoint defaults to a 32-frame uniform sampling cap. The runner disables sampling for predecoded frames and counts expanded processor tokens. Spoken-video visual frames and audio are explicitly decoded into separate inputs; no convenience video call is assumed to include a soundtrack. The AAC soundtrack produced a 2.624-second decoded waveform, so production timing maps must account for codec padding.

OCR recovered the expected scanned instruction. The earlier ASR smoke check recovered the expected sentence with word timestamps: 2.144 seconds to transcribe 2.566 seconds of synthetic speech. Full timestamp alignment, noisy recordings and multilingual quality remain later evaluation work.

## Renderer fix and verification

The original startup failure had two packaging causes. The library search path selected UNO libraries outside LibreOffice's program directory, so relative bootstrap lookup failed. After fixing that order, the package's `/etc` registry was empty because extraction does not execute package post-install scripts. Pointing the local bootstrap at the bundled `.registry` files resolved the configuration error. LibreOffice's bootstrap code resolves its UNO configuration relative to the loaded library. [Upstream bootstrap path implementation](https://raw.githubusercontent.com/LibreOffice/core/libreoffice-24.2.7.2/cppuhelper/source/paths.cxx).

Headless conversion also needs local Unix socket IPC. The tool sandbox denies socket binding; this was reproduced with a minimal socket probe. The renderer now reports that requirement directly. Conversion passed in an IPC-enabled execution environment without installing system packages.

The generated DOCX converted into one A4 PDF page. Its header and instruction survived text extraction, DejaVu Sans was embedded, and visual inspection confirmed the two lines were legible. The runner deletes stale output before conversion. The complete conversion regression passed from fresh package extraction.

The local extraction still emits optional Java and liblangtag data-path warnings. They did not prevent this English fixture from rendering. A deployment image should install the pinned packages into their normal locations, retain their data/fonts/notices, allow local IPC and keep outbound network access restricted as appropriate. Complex layout, other languages and byte-for-byte PDF determinism are not established here.

## Compatibility and license records

Sentence Transformers 6.1.0 needs Hugging Face Hub below 2.0; the lock resolves 1.33.0. Torchvision is required by the video processor. PyAV 19.0.1 was incompatible with the `metadata_errors` argument used by faster-whisper 1.2.1; pinning PyAV 16.1.0 resolved decoding.

The cached embedding checkpoint declares Apache 2.0 and the ASR checkpoint declares MIT. Tesseract and English data declare Apache 2.0. The actual FFmpeg codec build reports LGPL version 3 or later. Preserve full dependency notices with distribution artifacts. [Embedding model card](https://huggingface.co/google/embeddinggemma-2), [ASR card](https://huggingface.co/Systran/faster-whisper-small.en), [Tesseract](https://github.com/tesseract-ocr/tesseract), [FFmpeg licensing](https://ffmpeg.org/legal.html).

LibreOffice, fonts and their dependent libraries retain their package notices in the local extraction. Fixture speech uses the installed eSpeak NG 1.51 distribution. This synthetic-data generator is separate from application ASR.

## Phase 0 gates

| Gate | State |
|---|---|
| Exact checkpoint/processor and compatible CPU runtime pinned | Passed |
| Connector, evidence, embedding, publication and search contracts | Defined and tested |
| Finite normalized 768d vectors for every required input class | Passed with the full model |
| Cross-modal retrieval sanity | Passed on the eight-vector synthetic corpus |
| Measured overflow splitting without dropped frames | Passed |
| CPU latency, batch-one media throughput and peak memory | Recorded; larger-load testing remains Phase 7 |
| GPU resource report | CUDA unavailable; no GPU performance claim |
| OCR and local ASR | Passed on synthetic fixtures |
| DOCX renderer startup, conversion, page/text/font checks | Passed with local IPC allowed |

## Next phase

Phase 1 can establish Compose services, persistence, identity/access boundaries and migrations once requested. GPU execution needs a separate CUDA-compatible dependency lock and hardware validation if it becomes a supported target. Phase 7 retains the real-corpus quality gates, filtered ANN tests, concurrency measurements, long-media throughput and recovery/security suites.

Commands are in [evaluation/README.md](../evaluation/README.md). Current evidence: [full CPU run](../evaluation/reports/cpu-multimodal-2026-10-18.json), [vision run](../evaluation/reports/cpu-vision-2026-10-18.json), [audio run](../evaluation/reports/cpu-audio-2026-10-18.json), [GPU availability](../evaluation/reports/gpu-availability-2026-10-18.json), [renderer](../evaluation/reports/renderer.json) and [OCR/ASR](../evaluation/reports/auxiliary.json). The 16 October reports remain as historical measurements. See also [the decision record](decisions/0001-phase0-runtime-and-contracts.md).
