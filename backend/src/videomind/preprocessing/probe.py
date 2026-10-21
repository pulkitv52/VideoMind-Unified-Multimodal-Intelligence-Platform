"""Isolated format probe: no extraction, inference, or external-resource loading."""

import json
from pathlib import Path
import sys
import zipfile


def probe(path, mime):
    if mime in {"text/plain", "text/markdown"}:
        return {"format_validated": True}
    if mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ValueError("ENCRYPTED_PDF")
        count = len(reader.pages)
        if not 0 < count <= 1000:
            raise ValueError("PAGE_BUDGET_EXCEEDED")
        return {"page_count": count}
    if "wordprocessingml" in mime:
        from xml.etree import ElementTree

        with zipfile.ZipFile(path) as archive:
            entry = archive.getinfo("word/document.xml")
            if entry.file_size > 8 * 1024**2:
                raise ValueError("DOCUMENT_BUDGET_EXCEEDED")
            data = archive.read(entry)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValueError("UNSAFE_DOCUMENT")
            ElementTree.fromstring(data)
        return {"format_validated": True}
    if mime.startswith("image/"):
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 16_000_000
        with Image.open(path) as image:
            w, h = image.size
            if w * h > 16_000_000:
                raise ValueError("PIXEL_BUDGET_EXCEEDED")
            image.verify()
        return {"width": w, "height": h}
    import av

    with open(path, "rb") as stream, av.open(stream, mode="r") as media:
        videos = [s for s in media.streams if s.type == "video"]
        audios = [s for s in media.streams if s.type == "audio"]
        if mime.startswith("video/") and not videos:
            raise ValueError("NO_VIDEO_TRACK")
        if mime.startswith("audio/") and not audios:
            raise ValueError("NO_AUDIO_TRACK")
        if not videos and not audios:
            raise ValueError("NO_MEDIA_TRACK")
        if any(s.width * s.height > 16_000_000 for s in videos):
            raise ValueError("PIXEL_BUDGET_EXCEEDED")
        # Decode one frame to reject broken payloads; full timeline decoding is a later phase.
        for s in videos[:1] + audios[:1]:
            media.seek(0)
            try:
                next(media.decode(s))
            except StopIteration:
                raise ValueError("EMPTY_MEDIA_TRACK") from None
        return {
            "duration_ms": int(media.duration / 1000) if media.duration else None,
            "video_tracks": len(videos),
            "audio_tracks": len(audios),
        }


if __name__ == "__main__":
    try:
        result = probe(Path(sys.argv[1]), sys.argv[2])
        print(json.dumps({"ok": True, "metadata": result}))
    except Exception as exc:
        # Parser exceptions can contain imported text or paths.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": (
                        "DOCUMENT_ENCRYPTED"
                        if isinstance(exc, ValueError) and str(exc) == "ENCRYPTED_PDF"
                        else "STRUCTURAL_VALIDATION_FAILED"
                    ),
                }
            )
        )
        sys.exit(1)
