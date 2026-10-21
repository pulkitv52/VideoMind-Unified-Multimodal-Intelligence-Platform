"""Bounded, isolated normalization of transient image-query inputs."""

import base64
import binascii
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from fastapi import HTTPException

MAX_BYTES = 4 * 1024**2
MAX_BODY = 6 * 1024**2
MAX_ENCODED = 4 * ((MAX_BYTES + 2) // 3)


def normalize(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "Invalid image encoding") from None
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(413, "Query image must be at most 4 MiB")
    with tempfile.TemporaryDirectory(prefix="vm-query-") as directory:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "videomind.retrieval.image_query", directory],
                input=raw,
                capture_output=True,
                timeout=10,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"},
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                422, "Image decoding exceeded its processing budget"
            ) from None
    if result.returncode == 3:
        raise HTTPException(503, "Image decoder sandbox unavailable")
    if result.returncode or not result.stdout or len(result.stdout) > 2 * 1024**2:
        raise HTTPException(
            422, "Use a valid, still JPEG or PNG image of at most 8 million pixels"
        )
    return base64.b64encode(result.stdout).decode("ascii")


def main():
    from PIL import Image, ImageOps
    from videomind.preprocessing.sandbox import restrict

    Image.init()
    try:
        restrict(
            Path(sys.argv[1]),
            memory_bytes=256 * 1024**2,
            cpu_seconds=5,
            file_bytes=2 * 1024**2,
        )
    except Exception:
        raise SystemExit(3)
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("size")
        with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG")) as source:
            if (
                source.width * source.height > 8_000_000
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ValueError("image bounds")
            source.load()
            ImageOps.exif_transpose(source, in_place=True)
            source.thumbnail((640, 640))
            image = source.convert("RGB")
            image.info.clear()
            # Re-encoding discards EXIF and other input metadata.
            image.save(sys.stdout.buffer, format="PNG")
    except Exception:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
