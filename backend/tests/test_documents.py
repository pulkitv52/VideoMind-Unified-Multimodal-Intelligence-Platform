"""Real parser/OCR/rendering and sandbox acceptance checks, CPU only."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest
from pypdf import PdfReader, PdfWriter

from document_fixtures import make_pdf, make_docx
from videomind.connectors.upload.validation import InvalidFile
from videomind.preprocessing.documents.extract import (
    chunks,
    docx_structure,
    text_page,
    DocumentError,
)
from videomind.preprocessing.documents.profile import CONFIG, PROFILE
from videomind.preprocessing.documents.worker import run_extractor

RUNTIME = shutil.which("libreoffice") is not None
requires_runtime = pytest.mark.skipif(
    not RUNTIME, reason="run in Compose verify document runtime"
)


def test_text_offsets_preserve_unicode_crlf_and_markdown_sections(tmp_path):
    original = (
        "## Emergency\r\n\r\nCafé 😀 safety\r\n| Item | Action |\r\n| Pump | Stop |\r\n"
    )
    path = tmp_path / "original"
    path.write_bytes(original.encode())
    page = text_page(path, "text/markdown", tmp_path)
    assert (tmp_path / page["text_file"]).read_bytes() == original.encode()
    assert len(page["chunks"]) >= 4
    for c in page["chunks"]:
        assert original[c["start"] : c["end"]] == c["text"]
        assert c["end"] - c["start"] <= CONFIG["chunk_chars"]


def test_long_text_splits_without_truncation_and_preserves_offsets(tmp_path):
    text = "x" * 5001
    path = tmp_path / "original"
    path.write_text(text)
    page = text_page(path, "text/plain", tmp_path)
    assert "".join(c["text"] for c in page["chunks"]) == text
    assert len(page["chunks"]) == 4
    path.write_text("x" * (CONFIG["max_text_chars"] + 1))
    with pytest.raises(DocumentError, match="DOCUMENT_TEXT_LIMIT"):
        text_page(path, "text/plain", tmp_path)


def test_docx_structural_anchors_and_external_resource_rejection(tmp_path):
    path = make_docx(tmp_path / "original.docx")
    blocks = docx_structure(path)
    assert any(
        b["kind"] == "table_row" and b["text"] == "Equipment\tDaily check"
        for b in blocks
    )
    assert blocks[0]["style"] == "Heading1" and blocks[0]["anchor"] == "body/0"
    make_docx(path, external=True)
    with pytest.raises(DocumentError, match="EXTERNAL_DOCUMENT_RESOURCE"):
        docx_structure(path)


@requires_runtime
def test_pdf_sections_tables_multipage_and_rotated_boxes(tmp_path):
    path = make_pdf(
        tmp_path / "original",
        [
            {
                "lines": [
                    (50, 740, "Hospital safety procedure"),
                    (50, 700, "Equipment       Daily check"),
                    (50, 670, "Pump                 Stop"),
                ]
            },
            {"lines": [(50, 740, "Second page emergency instructions")]},
        ],
        rotation=90,
    )
    result = run_extractor(tmp_path, "application/pdf")
    assert len(result["pages"]) == 2 and result["profile"] == PROFILE
    for page in result["pages"]:
        text = (tmp_path / page["text_file"]).read_text()
        assert page["tiles"]
        for c in page["chunks"]:
            assert c["text"] == text[c["start"] : c["end"]]
            x0, y0, x1, y1 = c["box"]
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    assert "Hospital" in "".join(c["text"] for c in result["pages"][0]["chunks"])
    assert "Second" in "".join(c["text"] for c in result["pages"][1]["chunks"])


@requires_runtime
def test_scanned_and_mixed_pdf_ocr_keeps_raster_text_and_deduplicates_digital(tmp_path):
    make_pdf(
        tmp_path / "original",
        [
            {
                "scan": "EMERGENCY PROCEDURE\nSwitch off the power before\nopening the safety panel."
            },
            {
                "lines": [
                    (
                        50,
                        740,
                        "Digital heading with enough characters to pass text threshold",
                    )
                ],
                "scan": "MIXED PAGE\nInspect the pump daily.",
            },
        ],
    )
    result = run_extractor(tmp_path, "application/pdf")
    scan, mixed = result["pages"]
    assert scan["ocr"] and mixed["ocr"]
    assert "power" in " ".join(
        c["text"].lower() for c in scan["chunks"] if c["method"] == "ocr"
    )
    assert "pump" in " ".join(
        c["text"].lower() for c in mixed["chunks"] if c["method"] == "ocr"
    )
    assert sum("Digital heading" in c["text"] for c in mixed["chunks"]) == 1


@requires_runtime
def test_pinned_docx_rendering_and_structure(tmp_path):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        tmp_path = Path(folder)
        make_docx(tmp_path / "original.docx")
        result = run_extractor(
            tmp_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    assert result["rendering_file"] and result["structure_file"]
    assert len(result["pages"]) == 2
    assert any("Equipment" in c["text"] for c in result["pages"][0]["chunks"])
    assert any("Switch off" in c["text"] for c in result["pages"][1]["chunks"])


@requires_runtime
@pytest.mark.parametrize(
    "case,expected",
    [
        ("corrupt", "DOCUMENT_CORRUPT"),
        ("encrypted", "DOCUMENT_ENCRYPTED"),
        ("pages", "DOCUMENT_PAGE_LIMIT"),
        ("external", "EXTERNAL_DOCUMENT_RESOURCE"),
    ],
)
def test_document_failures_are_actionable(tmp_path, case, expected):
    mime = "application/pdf"
    if case == "corrupt":
        (tmp_path / "original").write_bytes(b"%PDF-1.7\nbroken")
    elif case == "external":
        make_docx(tmp_path / "original.docx", external=True)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        writer = PdfWriter()
        for _ in range(51 if case == "pages" else 1):
            writer.add_blank_page(600, 800)
        if case == "encrypted":
            writer.encrypt("secret")
        writer.write(tmp_path / "original")
    with pytest.raises(InvalidFile) as failure:
        run_extractor(tmp_path, mime)
    assert failure.value.code == expected


@requires_runtime
def test_sandbox_denies_network_parent_environment_and_writes_outside_workdir(tmp_path):
    code = """
import json,os,socket,sys
from pathlib import Path
from videomind.preprocessing.documents.sandbox import restrict
root=Path(sys.argv[1]);restrict(root)
denied=[]
for action in (lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM),lambda:socket.socket(socket.AF_INET6,socket.SOCK_STREAM),lambda:Path('/proc/'+str(os.getppid())+'/environ').read_bytes(),lambda:Path('/tmp/forbidden-document-test').write_text('denied')):
 try: action()
 except OSError as exc: denied.append(exc.errno in (1,13,30))
 else: denied.append(False)
(root/'proof.json').write_text(json.dumps(denied))
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, timeout=10)
    assert json.loads((tmp_path / "proof.json").read_text()) == [True] * 4


@requires_runtime
def test_extractor_wall_deadline_kills_the_real_process_group(tmp_path, monkeypatch):
    make_pdf(tmp_path / "original", [{} for _ in range(50)])
    monkeypatch.setitem(CONFIG, "wall_seconds", 0.01)
    with pytest.raises(InvalidFile) as failure:
        run_extractor(tmp_path, "application/pdf")
    assert failure.value.code == "DOCUMENT_TIMEOUT"


@requires_runtime
def test_oversized_pdf_page_rejected_before_rasterization(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(20000, 20000)
    writer.write(tmp_path / "original")
    with pytest.raises(InvalidFile) as failure:
        run_extractor(tmp_path, "application/pdf")
    assert failure.value.code == "DOCUMENT_PAGE_SIZE_LIMIT"


@pytest.mark.parametrize("case", ["span", "box", "profile"])
def test_parent_rejects_invalid_evidence_manifest_before_publication(tmp_path, case):
    from videomind.preprocessing.documents.contracts import validate_manifest

    (tmp_path / "page-1.txt").write_text("original evidence")
    page = {
        "page": 1,
        "text_file": "page-1.txt",
        "image_file": None,
        "width": None,
        "height": None,
        "lines": [],
        "chunks": [
            {
                "start": 0,
                "end": 8,
                "text": "original",
                "box": None,
                "method": "extracted",
                "structure": "paragraph-0",
            }
        ],
        "tiles": [],
        "ocr": False,
    }
    value = {
        "profile": PROFILE,
        "configuration": CONFIG,
        "pages": [page],
        "warnings": [],
        "rendering_file": None,
        "structure_file": None,
    }
    assert (
        validate_manifest(value, tmp_path)["pages"][0]["chunks"][0]["text"]
        == "original"
    )
    if case == "span":
        page["chunks"][0]["end"] = 100
    elif case == "box":
        page["chunks"][0]["box"] = [0, 0, 1, 1]
    else:
        value["profile"] = "0" * 64
    with pytest.raises(InvalidFile, match="DOCUMENT_MANIFEST_INVALID"):
        validate_manifest(value, tmp_path)
