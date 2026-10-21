# Evaluation tools

Run commands from the repository root. The Python target is 3.12 on Linux x86-64. Model files and environments stay local and are excluded from source control. Phase 0 uses synthetic fixtures; Phase 7 also contains licensed dataset metadata and retrieved snippets. Reports may contain source content and require review before sharing.

## Phase 7 local evaluation

Read [the protocol and measured limitations](../docs/phase7-validation.md). The frozen 46-asset corpus and 30 provisional queries are diagnostic data, not the required independently adjudicated release set. The [review worksheet](annotations/phase7-review.md) records unresolved labels.

`quality/` separates corpus freezing, publisher label parsing, metrics, HTTP search comparisons, native-video ablations, operator inference, resource/performance measurement and isolated restore rehearsals. No evaluation-only content route or inference service is exposed.

```bash
backend/.venv/bin/python scripts/evaluate.py freeze
backend/.venv/bin/python scripts/evaluate.py search
backend/.venv/bin/python scripts/evaluate.py ablate
backend/.venv/bin/python scripts/evaluate.py performance
backend/.venv/bin/python scripts/evaluate.py resources
backend/.venv/bin/python scripts/evaluate.py recovery
backend/.venv/bin/python -m pytest evaluation/tests/test_quality.py -q
python3 scripts/dev.py verify
backend/.venv/bin/python scripts/evaluate.py assess
```

Run model experiments and performance checks serially. `performance` restarts only the embedding process; operating-system file caches remain uncontrolled. `recovery` creates a coordinated private backup and restores disposable database/bucket targets, then removes those targets. Backups under `.local/backups` contain credentials and content; preserve their private permissions. The drill does not configure scheduled backups or a durable primary deletion journal.

`freeze` verifies an existing snapshot without overwriting labels and rejects changed corpora. For a new corpus, create a separate version of the manifests and qrels. Search runs overwrite `phase7-search.json`; preserve earlier runs first. `assess` compares the retained before/after runs and reads the recorded verification, performance and recovery reports. It leaves the original release gates open when labels, measurements or requirements are missing.

## Phase 0 feasibility checks

## Install and cache

```bash
UV_CACHE_DIR=.cache/uv uv sync --project backend --frozen --extra feasibility --extra transcription
backend/.venv/bin/python -m evaluation.runners.cache_models
```

The cache command downloads the immutable revisions in `manifests/model-revisions.json`. It needs network access. The smoke runners use cached models and default to offline mode. Their caches are under the repository's `.cache/huggingface` directory.

Generate the small document, scanned page, moving-square videos, speech and beep inputs:

```bash
backend/.venv/bin/python -c 'from pathlib import Path; from evaluation.runners.fixtures import generate; generate(Path("evaluation/fixtures/generated"))'
```

Fixture generation uses the system `libespeak-ng` library and English voice data (tested Ubuntu packages `libespeak-ng1` and `espeak-ng-data`, both `1.51+dfsg-12build1`) and DejaVu Sans at `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`. It records file hashes and generator package versions. The speech is synthetic. The spoken video deliberately combines that speech with the moving-square fixture; it is useful for track handling, not audiovisual semantic agreement.

## Run checks

```bash
backend/.venv/bin/python -m pytest backend/tests evaluation/tests -q
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 backend/.venv/bin/python -m evaluation.runners.phase0 --encoders text --report evaluation/reports/cpu-text.json
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 backend/.venv/bin/python -m evaluation.runners.phase0 --report evaluation/reports/cpu-multimodal.json
```

The default full-model run releases preprocessing allocator arenas and checks available memory before loading weights. Insufficient memory writes an incomplete report and exits with status 1. `--processor-only` prepares all media without validating embeddings and also returns an incomplete result. `--encoders vision` and `--encoders audio` support separate investigations. Every run records active encoders, checkpoint/profile hashes, source hashes, fixture hashes, token counts and hardware. Full runs include spoken-video visual/audio views and a small unified dense retrieval check. Media timing uses batch size one.

A passing text-only smoke report leaves the full-modality gate open. Three short query measurements cannot establish p95 platform latency, corpus throughput or general retrieval quality. Peak process RSS includes preprocessing and model loading. No actual source connector, database, API or access-control implementation is included in Phase 0.

For GPU validation, prepare a separate environment with compatible CUDA wheels and record its lock. The current lock points at CPU-only PyTorch/Torchvision. A `--device cuda` run requires that GPU environment; changing the flag alone does not add GPU support.

## Local OCR and ASR

The OCR check uses extracted Ubuntu 24.04 packages. This downloads packages into the repository cache without installing them globally:

```bash
mkdir -p .cache/system-debs .cache/system-tools
(cd .cache/system-debs && apt-get download tesseract-ocr=5.3.4-1build5 libtesseract5=5.3.4-1build5 liblept5=1.82.0-3build4 tesseract-ocr-eng=1:4.1.0-2)
for package in .cache/system-debs/*.deb; do dpkg-deb -x "$package" .cache/system-tools; done
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 backend/.venv/bin/python -m evaluation.runners.auxiliary
```

This packaging test assumes the host's remaining runtime libraries are available. Exact package availability may change in the Ubuntu archive; preserve the recorded checksums and use an approved archive snapshot if necessary. The runner reports OCR text, transcription/word timestamps, duration and actual FFmpeg build/license. Its LibreOffice field describes whether a system executable is installed; the separate renderer report records the project-local attempt.

## Document renderer packaging probe

The exact LibreOffice dependency versions are in `manifests/libreoffice-packages.json`. Download them into the same cache, then run the packaging probe:

```bash
python3 - <<'PY'
import json, subprocess
from pathlib import Path
packages = json.loads(Path('evaluation/manifests/libreoffice-packages.json').read_text())
subprocess.run(['apt-get', 'download', *[f"{p['name']}={p['version']}" for p in packages]], cwd='.cache/system-debs', check=True)
PY
backend/.venv/bin/python -m evaluation.runners.renderer
```

The probe extracts packages locally, puts LibreOffice's program directory first in the library search path, and uses the bundled read-only registry instead of unpopulated post-install registry links. It converts a generated DOCX into PDF and checks page count, text and the embedded DejaVu Sans font. Stale PDF output is removed before each run. Results and package/font hashes are in `reports/renderer.json`.

LibreOffice requires local Unix socket IPC even for offline headless conversion. The restrictive tool sandbox denies socket binding; the runner reports that requirement, and the conversion regression skips there. In an environment with local IPC allowed, the full suite passes 27 tests, including DOCX conversion. No internet connection is needed during conversion. The extracted build still emits optional Java and liblangtag data-path warnings; the English fixture passes, while multilingual rendering remains unverified.

## Decisions and results

See [the feasibility report](../docs/phase0-feasibility.md) for measured results and remaining gates. [The Phase 0 decision record](../docs/decisions/0001-phase0-runtime-and-contracts.md) explains the runtime pins and processor settings. Tests validate contract invariants; they do not establish database isolation or retrieval quality across modalities.

## Small video intake collection

See [the 30-video pack](../docs/video30-dataset.md) for CAVIAR store/lobby, UR Fall staged activities, and day/night Roadscapes samples. Preparation preserves upstream files and frame mappings; import exercises the existing intake only. It does not measure retrieval quality.

## Action and temporal pilot

`action_temporal/` implements AT0 review preparation and AT1 offline comparisons. See [the protocol, results and commands](../docs/action-temporal-validation.md) and [human review worksheet](annotations/action-temporal-v1-review.md). Run the commands in the linked validation document serially from the repository root. The `windows` action accepts one recipe name per invocation: `uniform12`, `short4` or `fine2`.

Window batches cap fresh encoding at 32 windows and are resumable. Partial metrics are withheld. All new vectors stay private and never publish into the live generation. A lower trial floor or an above-cutoff example is not a calibrated action detector. Preserve the frozen protocol/splits and complete human review before promotion.
