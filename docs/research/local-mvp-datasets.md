# Datasets for the local MVP

Checked against publisher documentation on 2026-10-18. Start with the existing generated fixtures and two small public files. This gives us format coverage without downloading a training corpus or loading a model during upload tests.

## Ready to try

The public samples are downloaded to `.local/datasets/public-starter/`. Their manifest records the source URL, byte count, SHA-256 and attribution. Total downloaded media is 681,556 bytes (about 666 KiB). These are local demonstration inputs, not a representative evaluation set.

| File | Content | Provenance and license | Exact bytes / SHA-256 |
| --- | --- | --- | --- |
| `dog.wav` | Five seconds of dog barking; mono WAV, 44.1 kHz | ESC-10, curated by K. J. Piczak; original `rose_bark.wav` by nfrae. ESC-10 is CC BY 3.0; the original recording is CC0. | 441,044 / `f40a849a2375c8c63312a73dd2dd6c74007301fcc21b4be2ece29a642831e3d8` |
| `chelsea.png` | A cat photograph, 451 × 300 | Stefan van der Walt, distributed by scikit-image under CC0. | 240,512 / `596aa1e7cb875eb79f437e310381d26b338a81c2da23439704a73c4651e8c4bb` |

ESC-50's publisher describes 2,000 five-second clips and its preassigned folds. Its metadata marks `1-100032-A-0.wav` as `esc10=True`, category `dog`, fold 1. The full ESC-50 collection has a noncommercial restriction; use only the explicitly marked ESC-10 subset for a reusable starter collection. Keep the individual credit with the file. [Publisher repository](https://github.com/karolpiczak/ESC-50), [pinned metadata](https://raw.githubusercontent.com/karolpiczak/ESC-50/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/meta/esc50.csv), [pinned license and individual credits](https://raw.githubusercontent.com/karolpiczak/ESC-50/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/LICENSE).

The cat photograph has an explicit CC0 declaration in scikit-image's data documentation. Its download uses a release tag; the recorded SHA-256 is the integrity check if upstream tags change. [Publisher documentation](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.chelsea).

Direct media downloads:

- [ESC-10 dog WAV, immutable repository revision](https://raw.githubusercontent.com/karolpiczak/ESC-50/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/audio/1-100032-A-0.wav)
- [Chelsea PNG, scikit-image v0.25.2](https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/chelsea.png)

The repository already has `evaluation/fixtures/generated/` with a scanned PDF/PNG, silent MP4, spoken MP4, synthetic speech WAV, beep WAV and procedure text. The renderer probe also generates a DOCX. Use these for deterministic document and track handling checks. The generated spoken video's speech and moving-square visuals intentionally describe different things, so it cannot measure audiovisual semantic agreement. Generation and provenance are documented in [evaluation/README.md](../../evaluation/README.md).

## Useful datasets after upload works

| Dataset | Useful for | Size, access and license | Recommendation |
| --- | --- | --- | --- |
| [LibriSpeech / OpenSLR 12](https://www.openslr.org/12/) | Speech transcription accuracy against reference text; short standalone speech inputs | Publisher lists `test-clean.tar.gz` at 346M and `dev-clean.tar.gz` at 337M, CC BY 4.0. No account gate appears on its download listing. | Later select 10–20 utterances with references and speaker IDs. Do not download the 6.3G training set for an MVP smoke test. |
| [DocLayNet](https://github.com/DS4SD/DocLayNet) | PDF page layouts, bounding boxes and evidence coordinates | 80,863 pages; core 28 GiB, extra PDF/text assets 7.5 GiB. [Publisher license](https://raw.githubusercontent.com/DS4SD/DocLayNet/main/LICENSE) is CDLA-Permissive 1.0, with notice/credit preservation conditions. | Later select about ten pages from different document categories using publisher-hosted subsets. Do not fetch full archives now. It supplies layout labels, not retrieval relevance judgments. |
| [Big Buck Bunny](https://peach.blender.org/download/) | Natural video, soundtrack, decoding, frame extraction and silent derivatives | Blender Foundation's [license page](https://peach.blender.org/about/) states CC BY 3.0 and attribution requirements. The download page points to official movie directories and warns that old links may have expired. | Keep as a candidate. Exact reachable file size and media checksums were not verified here; no film downloaded. It is not a spoken-dialogue ASR benchmark. |
| [Common Voice](https://commonvoice.mozilla.org/en/about) | Later multilingual speech and accent coverage | Mozilla says downloads require an email address; its [dataset listing](https://commonvoice.mozilla.org/fr/datasets) gives license and size per release/language. | Defer account-based downloads and large language bundles. Preserve the exact release and its terms when adopted. |

For a natural spoken video, a short user-owned recording with a known transcript is the most practical next addition. Record a 10–20 second explanation of the same procedure used in the document fixture, then retain its original and a derived silent copy with explicit parent/time mapping. No external spoken-video sample has been licensed and downloaded in this research pass.

## What to measure now

For ingestion, verify authenticated upload, accepted format, exact original checksum, immutable object storage, asset/revision creation, durable job state and source-scoped access. Retry the same input and restart a worker to check duplicate handling. Include unsupported, truncated and oversized files as negative cases. Record actual counts and durations in a run report.

Phase 2 can demonstrate registration and preservation of original files. It does not establish OCR, transcription, embeddings, semantic search or citation quality. An uploaded asset must not be presented as searchable until those stages have completed.

## UR Fall synchronization check

Checked the [publisher description](https://fenix.ur.edu.pl/mkepski/ds/uf.html)
and two tiny original CSVs on 18 October 2026, without downloading media archives:
[fall-01-data.csv](https://fenix.ur.edu.pl/mkepski/ds/data/fall-01-data.csv)
and [adl-01-data.csv](https://fenix.ur.edu.pl/mkepski/ds/data/adl-01-data.csv).
Both are comma separated with **no header**. Column 1 is a one-based frame ID;
column 2 is elapsed milliseconds from the sequence start, not an epoch timestamp.
There is no separate camera-0 timestamp column. The fall CSV has a third column
for interpolated total accelerometer magnitude in g; the inspected ADL CSV has
only the frame and timestamp columns. Converters must accept both shapes.

Observed fall-01: 160 rows, beginning `(1, 0, 1.0249)`, `(2, 33, 1.0032)`,
`(3, 66, 1.0285)`, `(4, 100, 0.98591)` and ending `(160, 5305, 1.0591)`.
Observed adl-01: 150 rows, beginning `(1, 0)`, `(2, 33)`, `(3, 66)`,
`(4, 100)` and ending `(150, 4997)`. These are measured CSV values; do not
replace them with an assumed exact 30-fps clock. For camera-0 RGB, use frame ID
to map each PNG to its sequence-relative timestamp, preserving both in the
derivative mapping. The publisher names the RGB archive `fall-01-cam0-rgb.zip`
but does not document individual PNG names on the landing page; inspect and
validate actual archive entries locally before binding IDs by filename.

The publisher says camera streams are recorded independently and associated
using nearest timestamps. Do not claim strict synchronization between cameras,
or infer that row numbers describe perfectly simultaneous multi-camera captures.

For a smaller five-ADL starter selection, the publisher's aggregate
[camera-0 ADL feature CSV](https://fenix.ur.edu.pl/mkepski/ds/data/urfall-cam0-adls.csv)
was inspected across all 40 sequence IDs. Feature rows can omit early frames,
so their row count alone is not a sequence length. Ranking their maximum frame
IDs identified ADL24 and ADL28 as the shortest candidates. Their separate
synchronization CSVs then confirmed complete lengths. Archive sizes below were
verified by HEAD requests; the research check downloaded no archives.

| Sequence | Sync rows / last timestamp | RGB ZIP bytes | Official archive |
| --- | --- | ---: | --- |
| ADL24 | 70 / 2302 ms | 15,370,322 | [adl-24-cam0-rgb.zip](https://fenix.ur.edu.pl/mkepski/ds/data/adl-24-cam0-rgb.zip) |
| ADL28 | 85 / 2808 ms | 19,374,661 | [adl-28-cam0-rgb.zip](https://fenix.ur.edu.pl/mkepski/ds/data/adl-28-cam0-rgb.zip) |

Both [ADL24 synchronization](https://fenix.ur.edu.pl/mkepski/ds/data/adl-24-data.csv)
and [ADL28 synchronization](https://fenix.ur.edu.pl/mkepski/ds/data/adl-28-data.csv)
start with frame 1 at 0 ms and contain two columns. No sequence shorter than
70 frames was identified in the aggregate metadata. The activity subtype was
not determined from these numeric files; keep the generic ADL label until
visual inspection.

For later retrieval evaluation, build a separate set of at least 30 natural-language queries with human-reviewed relevant asset IDs and page/time anchors. Include visual-only questions, speech questions and non-speech sounds. Keep related derivatives together when splitting data. Measure Recall@k, nDCG@k, evidence localization and unauthorized-result count. ESC category labels and a successful upload alone cannot establish those results. These are proposed evaluation steps; no retrieval benchmark was run for this note.
