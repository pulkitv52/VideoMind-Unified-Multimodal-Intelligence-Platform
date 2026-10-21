"""Offline, bounded extraction. Invoked only inside the document sandbox."""

import csv
import io
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfReader

from .profile import CONFIG, PROFILE


class DocumentError(ValueError):
    pass


def command(args, timeout=30, first_run_restart=False):
    try:
        result = subprocess.run(
            args,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        # Direct soffice.bin avoids the splash helper's global /tmp IPC. A fresh
        # user profile requests one restart (81); the wrapper normally handles it.
        if result.returncode == 81 and first_run_restart:
            result = subprocess.run(
                args,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        if result.returncode:
            raise DocumentError("DOCUMENT_RENDER_FAILED")
    except subprocess.TimeoutExpired:
        raise DocumentError("DOCUMENT_TIMEOUT") from None
    except (OSError, subprocess.CalledProcessError):
        raise DocumentError("DOCUMENT_RENDER_FAILED") from None


def bounded_xml(data):
    if len(data) > 8 * 1024**2:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise DocumentError("UNSAFE_DOCUMENT")
    return ET.fromstring(data)


def docx_structure(path):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(e.file_size for e in entries) > 64 * 1024**2:
            raise DocumentError("DOCUMENT_ARCHIVE_LIMIT")
        for entry in entries:
            if entry.filename.endswith(".rels"):
                root = bounded_xml(archive.read(entry))
                if any(r.get("TargetMode") == "External" for r in root):
                    raise DocumentError("EXTERNAL_DOCUMENT_RESOURCE")
            if any(
                t in entry.filename for t in ("vbaProject", "embeddings/", "activeX/")
            ):
                raise DocumentError("UNSAFE_DOCUMENT")
        root = bounded_xml(archive.read("word/document.xml"))
        blocks = []
        body = root.find("w:body", ns)
        if body is None:
            raise DocumentError("INVALID_DOCUMENT")
        for index, el in enumerate(body):
            kind = el.tag.rsplit("}", 1)[-1]
            if kind == "p":
                text = "".join(t.text or "" for t in el.findall(".//w:t", ns))
                style = el.find("w:pPr/w:pStyle", ns)
                blocks.append(
                    {
                        "anchor": f"body/{index}",
                        "kind": "paragraph",
                        "style": (
                            style.get("{" + ns["w"] + "}val")
                            if style is not None
                            else None
                        ),
                        "text": text,
                    }
                )
            elif kind == "tbl":
                for row, tr in enumerate(el.findall("w:tr", ns)):
                    text = "\t".join(
                        "".join(t.text or "" for t in cell.findall(".//w:t", ns))
                        for cell in tr.findall("w:tc", ns)
                    )
                    blocks.append(
                        {
                            "anchor": f"body/{index}/row/{row}",
                            "kind": "table_row",
                            "text": text,
                        }
                    )
        if sum(len(b["text"]) for b in blocks) > CONFIG["max_text_chars"]:
            raise DocumentError("DOCUMENT_TEXT_LIMIT")
        return blocks


def normalized_box(box, width, height):
    x0, y0, x1, y1 = box
    coords = [
        max(0, min(1, x0 / width)),
        max(0, min(1, y0 / height)),
        max(0, min(1, x1 / width)),
        max(0, min(1, y1 / height)),
    ]
    return coords if coords[0] < coords[2] and coords[1] < coords[3] else None


def pdf_lines(path, page, directory):
    xml = directory / "layout.xhtml"
    command(
        [
            "pdftotext",
            "-f",
            str(page),
            "-l",
            str(page),
            "-bbox-layout",
            "-enc",
            "UTF-8",
            str(path),
            str(xml),
        ]
    )
    # Poppler emits a trusted XHTML doctype; input is generated locally, never external XML.
    data = xml.read_bytes()
    if len(data) > 8 * 1024**2:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    root = ET.fromstring(data)
    ns = {"h": "http://www.w3.org/1999/xhtml"}
    el = root.find(".//h:page", ns)
    if el is None:
        raise DocumentError("DOCUMENT_LAYOUT_FAILED")
    width, height = float(el.get("width")), float(el.get("height"))
    if not (0 < width <= 14400 and 0 < height <= 14400):
        raise DocumentError("DOCUMENT_PAGE_SIZE_LIMIT")
    lines = []
    for bi, block in enumerate(el.findall(".//h:block", ns)):
        for line in block.findall("h:line", ns):
            words = line.findall("h:word", ns)
            text = " ".join(w.text or "" for w in words)
            box = normalized_box(
                [float(line.get(k)) for k in ("xMin", "yMin", "xMax", "yMax")],
                width,
                height,
            )
            if text.strip() and box:
                lines.append(
                    {
                        "text": text,
                        "box": box,
                        "block": f"block-{bi}",
                        "method": "extracted",
                    }
                )
    xml.unlink(missing_ok=True)
    return width, height, lines


def ocr_lines(image, directory):
    output = directory / "ocr"
    command(["tesseract", str(image), str(output), "-l", "eng", "--psm", "3", "tsv"])
    tsv = output.with_suffix(".tsv")
    if tsv.stat().st_size > 8 * 1024**2:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    with Image.open(image) as img:
        width, height = img.size
    groups = {}
    for word in csv.DictReader(
        io.StringIO(tsv.read_text()), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        if word.get("level") != "5" or not word.get("text", "").strip():
            continue
        key = tuple(word[k] for k in ("block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(word)
    lines = []
    for key, words in groups.items():
        x0 = min(int(w["left"]) for w in words)
        y0 = min(int(w["top"]) for w in words)
        x1 = max(int(w["left"]) + int(w["width"]) for w in words)
        y1 = max(int(w["top"]) + int(w["height"]) for w in words)
        box = normalized_box([x0, y0, x1, y1], width, height)
        if box:
            lines.append(
                {
                    "text": " ".join(w["text"] for w in words),
                    "box": box,
                    "block": "ocr-" + "-".join(key[:2]),
                    "method": "ocr",
                    "confidence": sum(float(w["conf"]) for w in words) / len(words),
                }
            )
    tsv.unlink(missing_ok=True)
    return lines


def overlaps(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    return intersection / max((a[2] - a[0]) * (a[3] - a[1]), 1e-12) > 0.55


def has_raster(page):
    seen = set()

    def visit(resources, depth=0):
        if depth > 8 or len(seen) > 2000:
            raise DocumentError("DOCUMENT_RESOURCE_LIMIT")
        for value in (
            resources.get("/XObject", {}).get_object().values()
            if "/XObject" in resources
            else ()
        ):
            obj = value.get_object()
            ident = id(obj)
            if ident in seen:
                continue
            seen.add(ident)
            if obj.get("/Subtype") == "/Image":
                return True
            if "/Resources" in obj and visit(obj["/Resources"], depth + 1):
                return True
        return False

    return visit(page.get("/Resources", {}))


def assemble(lines):
    text = ""
    for line in lines:
        line["start"] = len(text)
        text += line["text"] + "\n"
        line["end"] = len(text) - 1
    return text


def chunks(lines, text):
    """Do not merge pages, layout blocks, OCR/digital provenance or table rows."""
    result = []
    group = []

    def flush():
        if not group:
            return
        start, end = group[0]["start"], group[-1]["end"]
        boxes = [l["box"] for l in group if l.get("box")]
        box = (
            [
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            ]
            if boxes
            else None
        )
        result.append(
            {
                "start": start,
                "end": end,
                "text": text[start:end],
                "box": box,
                "method": group[0]["method"],
                "structure": group[0]["block"],
            }
        )
        group.clear()

    for line in lines:
        if group and (
            line["block"] != group[-1]["block"]
            or line["method"] != group[-1]["method"]
            or line["end"] - group[0]["start"] > CONFIG["chunk_chars"]
        ):
            flush()
        if line["end"] - line["start"] > CONFIG["chunk_chars"]:
            flush()
            for start in range(line["start"], line["end"], CONFIG["chunk_chars"]):
                end = min(line["end"], start + CONFIG["chunk_chars"])
                result.append(
                    {
                        "start": start,
                        "end": end,
                        "text": text[start:end],
                        "box": line.get("box"),
                        "method": line["method"],
                        "structure": line["block"],
                    }
                )
        else:
            group.append(line)
    flush()
    return result


def text_page(path, mime, directory):
    if path.stat().st_size > 8 * 1024**2:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    text = path.read_text(encoding="utf-8")
    if len(text) > CONFIG["max_text_chars"]:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    # Preserve every original code point and its half-open offsets, including CRLF.
    with path.open(encoding="utf-8", newline="") as stream:
        text = stream.read()
    if len(text) > CONFIG["max_text_chars"]:
        raise DocumentError("DOCUMENT_TEXT_LIMIT")
    lines = []
    pos = 0
    block = 0
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        if not body.strip():
            block += 1
        else:
            if mime == "text/markdown" and (
                body.lstrip().startswith("#") or "|" in body
            ):
                block += 1
            lines.append(
                {
                    "text": body,
                    "start": pos,
                    "end": pos + len(body),
                    "block": f"paragraph-{block}",
                    "method": "extracted",
                }
            )
            if mime == "text/markdown" and (
                body.lstrip().startswith("#") or "|" in body
            ):
                block += 1
        pos += len(raw)
    target = directory / "page-1.txt"
    target.write_bytes(text.encode("utf-8"))
    return {
        "page": 1,
        "text_file": target.name,
        "image_file": None,
        "width": None,
        "height": None,
        "lines": lines,
        "chunks": chunks(lines, text),
        "tiles": [],
        "ocr": False,
    }


def check_budget(directory, pages):
    if (
        sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
        > CONFIG["max_output_bytes"] + 64 * 1024**2
    ):
        raise DocumentError("DOCUMENT_OUTPUT_LIMIT")
    if (
        sum(len(p["chunks"]) + len(p["tiles"]) + bool(p["image_file"]) for p in pages)
        > CONFIG["max_segments"]
    ):
        raise DocumentError("DOCUMENT_SEGMENT_LIMIT")
    if (
        sum(sum(len(l["text"]) + 1 for l in p["lines"]) for p in pages)
        > CONFIG["max_text_chars"]
    ):
        raise DocumentError("DOCUMENT_TEXT_LIMIT")


def extract(path: Path, mime: str, directory: Path):
    manifest = {
        "profile": PROFILE,
        "configuration": CONFIG,
        "pages": [],
        "warnings": [],
        "rendering_file": None,
        "structure_file": None,
    }
    if mime in ("text/plain", "text/markdown"):
        manifest["pages"] = [text_page(path, mime, directory)]
        if not manifest["pages"][0]["chunks"]:
            manifest["warnings"].append("DOCUMENT_NO_TEXT")
        return manifest
    pdf = path
    if "wordprocessingml" in mime:
        structure = docx_structure(path)
        structure_path = directory / "structure.json"
        structure_path.write_text(json.dumps(structure, ensure_ascii=False))
        manifest["structure_file"] = structure_path.name
        command(
            [
                "/usr/lib/libreoffice/program/soffice.bin",
                "-env:UserInstallation=" + (directory / "lo-profile").as_uri(),
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(directory),
                str(path),
            ],
            timeout=60,
            first_run_restart=True,
        )
        pdf = directory / (path.stem + ".pdf")
        if not pdf.is_file():
            raise DocumentError("DOCUMENT_RENDER_FAILED")
        manifest["rendering_file"] = pdf.name
    try:
        reader = PdfReader(pdf, strict=True)
        if reader.is_encrypted:
            raise DocumentError("DOCUMENT_ENCRYPTED")
        count = len(reader.pages)
        if not 0 < count <= CONFIG["max_pages"]:
            raise DocumentError("DOCUMENT_PAGE_LIMIT")
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("DOCUMENT_CORRUPT") from None
    for number, page in enumerate(reader.pages, 1):
        (directory / "progress.json").write_text(
            json.dumps(
                {"stage": "extract", "pages_done": number - 1, "pages_total": count}
            )
        )
        if any(
            not 0 < float(v) <= 14400
            for v in (page.mediabox.width, page.mediabox.height)
        ):
            raise DocumentError("DOCUMENT_PAGE_SIZE_LIMIT")
        width, height, lines = pdf_lines(pdf, number, directory)
        image = directory / f"page-{number}.png"
        command(
            [
                "pdftoppm",
                "-f",
                str(number),
                "-l",
                str(number),
                "-scale-to",
                str(CONFIG["page_edge"]),
                "-singlefile",
                "-png",
                str(pdf),
                str(image.with_suffix("")),
            ]
        )
        ocr = len("".join(l["text"] for l in lines).strip()) < 40 or has_raster(page)
        if ocr:
            digital = list(lines)
            for line in ocr_lines(image, directory):
                if any(overlaps(line["box"], d["box"]) for d in digital):
                    continue
                lines.append(line)
            if not lines:
                manifest["warnings"].append(f"PAGE_{number}_NO_TEXT")
        lines.sort(key=lambda l: (round(l["box"][1], 3), l["box"][0]))
        content = assemble(lines)
        text_file = directory / f"page-{number}.txt"
        text_file.write_text(content, encoding="utf-8")
        tiles = []
        with Image.open(image) as img:
            iw, ih = img.size
            if max(iw, ih) > 1536:
                step = CONFIG["tile_edge"] - CONFIG["tile_overlap"]
                for y in range(0, ih, step):
                    for x in range(0, iw, step):
                        x1, y1 = min(iw, x + CONFIG["tile_edge"]), min(
                            ih, y + CONFIG["tile_edge"]
                        )
                        target = directory / f"tile-{number}-{x}-{y}.png"
                        img.crop((x, y, x1, y1)).save(target)
                        tiles.append(
                            {
                                "file": target.name,
                                "box": [x / iw, y / ih, x1 / iw, y1 / ih],
                            }
                        )
        item = {
            "page": number,
            "text_file": text_file.name,
            "image_file": image.name,
            "width": width,
            "height": height,
            "lines": lines,
            "chunks": chunks(lines, content),
            "tiles": tiles,
            "ocr": ocr,
        }
        manifest["pages"].append(item)
        check_budget(directory, manifest["pages"])
    return manifest


def main():
    directory = Path(sys.argv[1]).resolve()
    from .sandbox import restrict

    try:
        restrict(directory)
        result = extract(
            (
                directory / "original.docx"
                if "wordprocessingml" in sys.argv[2]
                else directory / "original"
            ),
            sys.argv[2],
            directory,
        )
        (directory / "result.json").write_text(
            json.dumps({"ok": True, "manifest": result}, ensure_ascii=False)
        )
    except Exception as exc:
        codes = {
            "SANDBOX_UNAVAILABLE",
            "DOCUMENT_TIMEOUT",
            "DOCUMENT_RENDER_FAILED",
            "DOCUMENT_TEXT_LIMIT",
            "UNSAFE_DOCUMENT",
            "DOCUMENT_ARCHIVE_LIMIT",
            "EXTERNAL_DOCUMENT_RESOURCE",
            "INVALID_DOCUMENT",
            "DOCUMENT_LAYOUT_FAILED",
            "DOCUMENT_PAGE_SIZE_LIMIT",
            "DOCUMENT_ENCRYPTED",
            "DOCUMENT_PAGE_LIMIT",
            "DOCUMENT_CORRUPT",
            "DOCUMENT_OUTPUT_LIMIT",
            "DOCUMENT_SEGMENT_LIMIT",
            "DOCUMENT_RESOURCE_LIMIT",
        }
        code = str(exc) if str(exc) in codes else "DOCUMENT_EXTRACTION_FAILED"
        (directory / "result.json").write_text(
            json.dumps({"ok": False, "error_code": code})
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
