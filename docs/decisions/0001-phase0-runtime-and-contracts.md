# Phase 0 runtime and module contracts

Date: 16 October 2026. Updated: 18 October 2026. Status: adopted for local CPU feasibility; GPU execution remains unverified.

## Decisions

Use the modular backend layout in the architecture proposal. Connector discovery, preprocessing output, evidence locations, embedding profiles, publication manifests and search responses have separate Pydantic contracts. Shared code contains only small value types. These contracts validate structure and consistency; runtime authorization, database constraints and transactional publication belong to later phases.

Pin `google/embeddinggemma-2` and its processor to revision `914f7f89142e33e77833254d9c9b90c3cef7303b`. Use FP32 on this CPU host. `backend/uv.lock` pins Python dependencies and wheel hashes. Keep feasibility and transcription dependencies optional so importing domain contracts does not load PyTorch.

Use native media views independently of transcript/OCR views. Decode video frames explicitly and extract soundtrack audio separately. The pinned processor configuration has a default 32-frame cap with uniform sampling. Disable that sampling for predecoded feasibility inputs, count expanded processor tokens and split oversized inputs before inference. The observed frame token cost differs from the card's default estimate, so measured processor output controls admission.

Use `faster-whisper==1.2.1` with the pinned `Systran/faster-whisper-small.en` revision in the model manifest. CPU transcription uses INT8. Keep ASR separate from the embedding model. Pin `av==16.1.0`: the first smoke test with PyAV 19.0.1 failed because faster-whisper supplied the removed `metadata_errors` argument to `av.open`.

Use Tesseract 5.3.4 with pinned English trained data for the OCR feasibility check. Download and extract its Ubuntu packages into the project cache; leave the host package installation unchanged. Record package checksums. PyAV supplies the tested codec libraries.

The LibreOffice 24.2.7 extraction now passes startup and DOCX conversion checks. Its program directory must come first in the library search path, and local bootstrap must use the packaged `.registry` tree because extraction does not run package post-install scripts. Headless rendering needs local Unix socket IPC. Keep runtime/cache/profile data local and check page count, extracted text and the embedded DejaVu Sans font. Normal deployment packaging should install the binary/data packages into their standard image paths.

## Resource limits and consequences

This host exposes a Ryzen 7 7730U CPU. CUDA is unavailable in the current environment. On 16 October, available RAM was below 3 GiB; after memory was freed, the complete model passed on 18 October. The runner admits text-only CPU inference at 2 GiB available, vision at 3.5 GiB, audio at 4.5 GiB and full-model inference at 6 GiB. These are conservative admission limits. Linux allocator arenas freed by preprocessing are returned before checking the unchanged limit.

The full model passed vector validity and retrieval sanity checks for text, scanned pages, silent video, speech and non-speech sound. Spoken video is validated as separate visual and decoded soundtrack views. A unified eight-vector candidate pool passed three query checks. CPU visual encoding was slow on the fixture, so these results establish functional feasibility rather than a throughput promise. Measurements and remaining evaluation work are in [the feasibility report](../phase0-feasibility.md).

The validated hardware scope is local CPU execution. GPU validation requires suitable hardware and a separate compatible GPU dependency lock; the present lock uses CPU wheels. GPU performance and large-corpus retrieval remain unverified.
