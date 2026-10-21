"""Any producer, normalization, rendering or limit change requires a new profile."""

import hashlib
import json

CONFIG = {
    "version": "documents-v1",
    "packages_snapshot": "debian-bookworm-20261018T000000Z",
    "parser": "pypdf-6.12.0+poppler-bbox-layout",
    "renderer": "libreoffice-writer+DejaVuSans",
    "ocr": "tesseract-eng-psm3",
    "ocr_policy": "low-text-or-raster-page; discard duplicate digital lines",
    "coordinates": "display-page-normalized-top-left",
    "normalization": "unicode-codepoints; no Unicode normalization; per-line whitespace",
    "max_pages": 50,
    "max_text_chars": 2_000_000,
    "max_segments": 5000,
    "max_output_bytes": 96 * 1024**2,
    "page_edge": 2400,
    "tile_edge": 1200,
    "tile_overlap": 100,
    "chunk_chars": 1600,
    "wall_seconds": 180,
}
PROFILE = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()
DOCUMENT_MIMES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
)
