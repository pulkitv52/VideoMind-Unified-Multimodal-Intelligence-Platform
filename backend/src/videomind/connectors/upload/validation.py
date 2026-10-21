"""Bounded byte-level admission; full structural validation runs in a worker."""

from pathlib import PurePosixPath
import zipfile
import codecs

FORMATS = {
    ".pdf": ("application/pdf", "document"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "document",
    ),
    ".txt": ("text/plain", "document"),
    ".md": ("text/markdown", "document"),
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".mp4": ("video/mp4", "video"),
    ".webm": ("video/webm", "video"),
    ".mp3": ("audio/mpeg", "audio"),
    ".wav": ("audio/wav", "audio"),
    ".m4a": ("audio/mp4", "audio"),
    ".flac": ("audio/flac", "audio"),
    ".ogg": ("audio/ogg", "audio"),
}


class InvalidFile(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def filename(value):
    if (
        not value
        or len(value) > 200
        or "/" in value
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or value in {".", ".."}
    ):
        raise InvalidFile("INVALID_FILENAME")
    return value


def inspect(path, name):
    filename(name)
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in FORMATS:
        raise InvalidFile("UNSUPPORTED_FORMAT")
    with open(path, "rb") as stream:
        head = stream.read(8192)
    if not head:
        raise InvalidFile("EMPTY_FILE")
    valid = {
        ".pdf": head.startswith(b"%PDF-"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".mp4": head[4:8] == b"ftyp",
        ".m4a": head[4:8] == b"ftyp",
        ".webm": head.startswith(b"\x1aE\xdf\xa3"),
        ".wav": head.startswith(b"RIFF") and head[8:12] == b"WAVE",
        ".flac": head.startswith(b"fLaC"),
        ".ogg": head.startswith(b"OggS"),
        ".mp3": head.startswith(b"ID3")
        or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224),
    }
    if suffix in valid and not valid[suffix]:
        raise InvalidFile("FORMAT_MISMATCH")
    if suffix in {".txt", ".md"}:
        # Bound validation memory even when two maximum-size files arrive together.
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    if "\x00" in decoder.decode(block):
                        raise InvalidFile("BINARY_TEXT")
                decoder.decode(b"", final=True)
        except UnicodeError:
            raise InvalidFile("INVALID_UTF8") from None
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                info = archive.infolist()
                if len(info) > 1000 or sum(i.file_size for i in info) > 64 * 1024**2:
                    raise InvalidFile("DOCUMENT_BUDGET_EXCEEDED")
                if any(
                    i.file_size / max(i.compress_size, 1) > 200 or i.flag_bits & 1
                    for i in info
                ):
                    raise InvalidFile("UNSAFE_DOCUMENT")
                names = {i.filename for i in info}
                if not {"[Content_Types].xml", "word/document.xml"} <= names:
                    raise InvalidFile("INVALID_DOCX")
                if any(
                    "vbaProject" in n
                    or n.startswith("/")
                    or ".." in PurePosixPath(n).parts
                    for n in names
                ):
                    raise InvalidFile("UNSAFE_DOCUMENT")
        except (zipfile.BadZipFile, OSError):
            raise InvalidFile("INVALID_DOCX") from None
    return FORMATS[suffix]
