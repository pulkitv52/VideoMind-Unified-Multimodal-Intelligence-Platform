# Phase 3: document extraction and evidence

The user authorized Phase 3 on 19 October 2026. This phase adds document processing and inspection on the existing CPU-only laptop. The final release checks passed 105 tests in 104.18 seconds, plus strict TypeScript and the Vite production build. Measured results are in [the acceptance report](../evaluation/reports/phase3-completion.json).

## What users can do

Upload PDF, DOCX, UTF-8 TXT or Markdown through an existing collection, or sync an allowlisted folder. Format validation queues a separate document job. Existing stored documents are queued during migration. The file list shows extraction progress, a useful error with a retry action, or **Open document**.

The viewer shows a PDF page preview beside extracted passages. Selecting a passage highlights its page region. OCR text is labelled. TXT and Markdown show literal text with Unicode code-point spans; Markdown and document text are never interpreted as HTML. DOCX uses a stored PDF rendering and also retains structural paragraph/table-row anchors. Users can download the exact original revision or the rendered PDF.

Every passage and page/tile image has an opaque citation. Opening its link restores the same revision, segment set, page and passage. Replacing a file preserves old citations while that asset and its source remain accessible. Disconnecting a source or removing a folder asset makes its evidence unavailable immediately. Requests for document metadata, page images, text artifacts, original revisions and citations all reauthorize access.

## Processing and mappings

The `preprocessing/documents` module owns extraction, the pinned profile, sandbox and worker publication. `evidence/routes.py` resolves authorized evidence. Connector fetching, original intake and future embedding/retrieval stay separate.

PDF text comes from Poppler's layout boxes. Chunks stay within pages and layout blocks, with half-open offsets into a stored extracted-text artifact. Large blocks split at 1,600 code points. Tables retain their visible text and coordinate mapping; this is not a spreadsheet reconstruction engine. Rotated-page boxes use the displayed page's top-left coordinate system.

Low-text pages and pages containing raster images receive English Tesseract OCR. This includes mixed pages with a digital heading and a scanned region. OCR lines overlapping digital lines are discarded to avoid duplicate representations. Confidence values remain extractor metadata and are explicitly uncalibrated. Complex reading order, handwriting and multilingual OCR have no quality guarantee.

Each PDF or rendered DOCX page has a PNG representation capped at a 2,400-pixel long edge. Pages larger than 1,536 pixels also produce 1,200-pixel tiles with 100-pixel overlap and explicit normalized boxes. Page/tile images remain native image inputs for Phase 5. Text and OCR segments populate `searchable_text` as future retrieval inputs. Semantic search, embeddings and active generation publication remain Phases 5–6; `retrieval_ready` and the current document `searchable` flag stay false.

DOCX rendering uses LibreOffice's binary directly. A fresh profile can request one restart with status 81; the worker handles that once. IPC lives in the job's scratch directory. The [pinned LibreOffice IPC implementation](https://raw.githubusercontent.com/LibreOffice/core/libreoffice-7.4.7.2/sal/osl/unx/pipe.cxx) documents its socket-path selection. External DOCX relationships, embedded objects and macros are rejected. The layout manifest also has a 50,000-line per-page bound. A rendering failure leaves the original intact and reports an actionable failure; it does not invent page numbers.

## Bounds and runtime

The adopted laptop limits are 64 MiB per original, 50 PDF/rendered pages, two million extracted text code points, 5,000 segments, and 96 MiB of registered derivatives per document. Plain text has an 8 MiB byte guard before decoding. Page dimensions over 14,400 points are rejected before rasterization. Parsing has a three-minute wall deadline, a 120-second per-process CPU limit, a 1 GiB per-process address-space limit, 128 descriptors and a 32 MiB per-file output limit. The wall deadline kills the whole parser/renderer process group.

One solo worker processes heavy jobs at a time. Its container limit is 1.5 GiB with one CPU and a private 256 MiB scratch tmpfs. `/tmp` and the image remain read-only. Linux Landlock restricts filesystem reads to the job directory and public runtime files, with regular-file writes confined to the job directory. Seccomp permits Unix IPC and denies Internet socket creation, ptrace and cross-process memory reads. Parser children receive an allowlisted environment with no service credentials. Sandboxing fails closed when the required kernel facilities are unavailable. This deployment targets the tested Linux x86-64 host; portable desktop extraction needs separate validation.

Document producers are pinned through `documents/profile.py`, the Python lockfile, the backend image digest and Debian/ Debian-security snapshots dated 18 October 2026. The container installs Poppler, Tesseract English, LibreOffice Writer and DejaVu fonts in their normal paths. This adopts the reproducible Debian deployment packages rather than the project-local Ubuntu tools used during Phase 0. Each extraction records the profile and package-inventory fingerprint. Package versions, model/data/font hashes and notices are retained in the release report and image. Rendering reproducibility means a pinned producer and mapping, not byte-identical PDF output across platforms.

## Durability, access and cleanup

Document jobs reuse PostgreSQL scheduling, outbox events, three bounded attempts, five-minute leases, source cancellation and manual retries. The parser parent records progress and rechecks access every two seconds while parsing. Readiness accepts a fresh document heartbeat when the busy solo worker cannot answer a control ping; a missing worker's heartbeat ages out after ten seconds. This is a bounded liveness signal, not proof that arbitrary native code will succeed.

The parent validates sandbox output with Pydantic before admission, checks the pinned profile, page ordering, coordinate bounds, artifact names and exact text spans, and rechecks the original hash. Derived outputs receive quota reservations before storage writes. Publication holds the shared storage lock and workspace/source locks, checks the current lease and asset availability, then writes object references, pages, segments, evidence links, citations and searchable text in one transaction. The ready segment set and successful job status commit together. A stale task cannot publish. A killed writer leaves charged reservations and reclaimable objects, with no partial evidence. Retrying produces one complete set.

`document_pages` has forced source/workspace RLS and immutable runtime page metadata. Segment inputs reference derived objects. Page evidence retains its original object, revision, rendering profile and region; text evidence references a stored artifact and exact offsets. Citations select their original segment set even when a newer set exists. Original and rendered PDFs download as attachments; safe PNG previews are served inline with restrictive headers. Already delivered bytes remain with the client after revocation.

The existing one-hour retention floor applies to disconnected sources and removed assets. Maintenance retires unreferenced document derivatives before their originals, and preserves all referenced revision history. Failed-write reservations stay charged until storage cleanup confirms removal. Physical cleanup still depends on the stack running; backup retention remains Phase 7.

## Acceptance checks

The Compose suite exercises digital sections/tables, multiple pages, rotated pages, scanned and mixed pages, Unicode/CRLF spans, DOCX structural anchors and PDF rendering. Failure fixtures cover corruption, encryption, unsafe DOCX resources, page/text/size limits and an actual extraction deadline. The sandbox test attempts IPv4/IPv6 socket creation, parent-environment reads and out-of-directory writes.

Integration checks use the deployed database role and real MinIO. They resolve every segment in a mixed-page fixture, download its image, verify lexical input rows, retain a citation across replacement, revoke access in an existing session, reject guessed objects, disconnect a source and reject its evidence. Quota and stale-lease checks verify atomic publication. A real SIGKILL after a derivative PUT verifies recovery and reservation cleanup. Retention tests age only disposable fixtures; no wall-clock retention soak is claimed.

The final report records the test count and runtime, frontend build, browser evidence, retained originals, package versions and resource snapshot. OCR accuracy and document throughput on a representative user corpus remain evaluation work; this phase does not claim a retrieval benchmark.

## Completed local check

All 46 existing originals passed authenticated checksum verification, including all 30 dataset videos. Eight documents are ready, all 107 current citations resolved to their exact revisions and segment sets, and both page previews downloaded correctly. Browser checks covered the scanned-page highlight, reopening a stable citation, rendered DOCX evidence and plain-text character spans. The final UI also cleared temporary connection errors after service recovery.

The complete 105-test suite passed in 104.18 seconds against the real Compose services. Fresh migrations reached `0010_document_heartbeat`; all 27 application tables have forced RLS, and the deployed role has neither superuser nor BYPASSRLS privileges. One upstream Starlette/httpx TestClient deprecation warning remains. Frontend strict TypeScript and the production build passed.

The final stack reported every dependency ready and retrieval readiness false. The seven services used about 627.97 MiB in one post-verification Docker snapshot, with the embedding model unloaded. This is not a peak measurement. No GPU was used. See [preservation and producer versions](../evaluation/reports/phase3-preservation.json), [OCR viewer](../evaluation/reports/phase3-document-evidence.jpg) and [DOCX viewer](../evaluation/reports/phase3-docx-evidence.jpg).

To repeat the checks, run `python3 scripts/dev.py up`, `python3 scripts/dev.py verify`, then `backend/.venv/bin/python scripts/check_document_evidence.py` from the repository root after installing the backend development environment. The last command reads the existing demo corpus, verifies original hashes and citations, and records package/data/font hashes without printing credentials. It expects the 30-video demo pack to be present.
