"""Validate sandbox output before admitting objects or publishing evidence."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from videomind.connectors.upload.validation import InvalidFile
from .profile import CONFIG, PROFILE


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Line(Output):
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    block: str = Field(max_length=200)
    method: Literal["extracted", "ocr"]
    box: tuple[float, float, float, float] | None = None
    confidence: float | None = None


class Chunk(Output):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=1600)
    box: tuple[float, float, float, float] | None
    method: Literal["extracted", "ocr"]
    structure: str = Field(max_length=200)


class Tile(Output):
    file: str = Field(pattern=r"^tile-\d+-\d+-\d+\.png$")
    box: tuple[float, float, float, float]


class Page(Output):
    page: int = Field(ge=1, le=50)
    text_file: str = Field(pattern=r"^page-\d+\.txt$")
    image_file: str | None
    width: float | None = Field(gt=0, le=14400)
    height: float | None = Field(gt=0, le=14400)
    lines: list[Line] = Field(max_length=50000)
    chunks: list[Chunk] = Field(max_length=5000)
    tiles: list[Tile] = Field(max_length=16)
    ocr: bool


class Manifest(Output):
    profile: str
    configuration: dict
    pages: list[Page] = Field(min_length=1, max_length=50)
    warnings: list[str] = Field(max_length=51)
    rendering_file: Literal["original.pdf"] | None
    structure_file: Literal["structure.json"] | None


def valid_box(box):
    return box is not None and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1


def validate_manifest(value, directory: Path):
    try:
        output = Manifest.model_validate(value)
        if output.profile != PROFILE or output.configuration != CONFIG:
            raise ValueError("profile")
        total_chars = 0
        total_segments = 0
        for number, page in enumerate(output.pages, 1):
            if page.page != number or page.text_file != f"page-{number}.txt":
                raise ValueError("page")
            if page.image_file not in (None, f"page-{number}.png"):
                raise ValueError("image")
            if page.image_file and (not page.width or not page.height):
                raise ValueError("geometry")
            if not page.image_file and (
                page.width is not None or page.height is not None or page.tiles
            ):
                raise ValueError("geometry")
            path = directory / page.text_file
            if path.is_symlink() or path.stat().st_size > 8 * 1024**2:
                raise ValueError("text")
            content = path.read_bytes().decode("utf-8")
            total_chars += len(content)
            total_segments += len(page.chunks) + len(page.tiles) + bool(page.image_file)
            for span in [*page.lines, *page.chunks]:
                if (
                    not (0 <= span.start < span.end <= len(content))
                    or content[span.start : span.end] != span.text
                ):
                    raise ValueError("span")
                if (page.image_file and not valid_box(span.box)) or (
                    not page.image_file and span.box is not None
                ):
                    raise ValueError("box")
            for tile in page.tiles:
                if not valid_box(tile.box) or not tile.file.startswith(
                    f"tile-{number}-"
                ):
                    raise ValueError("tile")
        if (
            total_chars > CONFIG["max_text_chars"]
            or total_segments > CONFIG["max_segments"]
        ):
            raise ValueError("budget")
        return output.model_dump(mode="json", exclude_none=False)
    except (ValidationError, ValueError, OSError):
        raise InvalidFile("DOCUMENT_MANIFEST_INVALID") from None
