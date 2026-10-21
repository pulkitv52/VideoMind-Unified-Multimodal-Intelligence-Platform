"""Owned document fixtures; no downloaded content or external model needed."""

import io
from pathlib import Path
import zlib
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image, ImageDraw, ImageFont


def make_pdf(path, pages, rotation=0):
    """pages: [{lines:[(x,y,text)], scan:'text to rasterize'}]."""
    objects = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"",
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    kids = []
    for page in pages:
        content = []
        image_id = None
        for x, y, value in page.get("lines", []):
            escaped = (
                value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            )
            content.append(f"BT /F1 16 Tf {x} {y} Td ({escaped}) Tj ET")
        if page.get("scan"):
            img = Image.new("RGB", (1200, 600), "white")
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
            )
            draw.multiline_text(
                (50, 70), page["scan"], font=font, fill="black", spacing=18
            )
            raw = zlib.compress(img.tobytes())
            image_id = len(objects) + 1
            objects.append(
                f"<< /Type /XObject /Subtype /Image /Width 1200 /Height 600 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(raw)} >>\nstream\n".encode()
                + raw
                + b"\nendstream"
            )
            content.append(f"q 500 0 0 250 50 300 cm /Im1 Do Q")
        data = "\n".join(content).encode()
        content_id = len(objects) + 1
        objects.append(
            f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
        )
        page_id = len(objects) + 1
        kids.append(page_id)
        resources = "/Font << /F1 1 0 R >>" + (
            f" /XObject << /Im1 {image_id} 0 R >>" if image_id else ""
        )
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Rotate {rotation} /Resources << {resources} >> /Contents {content_id} 0 R >>".encode()
        )
    objects[1] = (
        f"<< /Type /Pages /Count {len(kids)} /Kids [".encode()
        + " ".join(f"{k} 0 R" for k in kids).encode()
        + b"] >>"
    )
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = output.tell()
    output.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer\n<< /Size {len(objects)+1} /Root 3 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    path.write_bytes(output.getvalue())
    return path


def make_docx(path, external=False):
    types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
    rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    doc = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="DejaVu Sans"/></w:rPr><w:t>Hospital safety procedure</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Equipment</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Daily check</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:br w:type="page"/><w:t>Switch off the power before opening the panel.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", doc)
        if external:
            archive.writestr(
                "word/_rels/document.xml.rels",
                """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" TargetMode="External" Target="https://example.invalid/private.png"/></Relationships>""",
            )
    return path
