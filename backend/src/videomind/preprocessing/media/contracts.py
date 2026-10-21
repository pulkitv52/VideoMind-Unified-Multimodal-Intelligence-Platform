"""Parent-side validation of untrusted decoder manifests and timeline mappings."""

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from videomind.connectors.upload.validation import InvalidFile
from .profile import CONFIG, PROFILE


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Frame(Item):
    file: str = Field(pattern=r"^frame-\d+\.jpg$")
    original_ms: int = Field(ge=0)
    pts: int
    time_base: tuple[int, int]


class Word(Item):
    word: str = Field(max_length=10000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class Segment(Item):
    representation: Literal["video", "audio", "transcript"]
    track: str = Field(pattern=r"^(video|audio):\d+$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    file: str = Field(pattern=r"^(visual-\d+\.json|audio-\d+-\d+\.wav|track-\d+\.wav)$")
    frames: list[Frame] = Field(max_length=20)
    text: str | None = Field(default=None, max_length=10000)
    words: list[Word] = Field(max_length=2000)


class Manifest(Item):
    profile: str
    configuration: dict
    origin_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    tracks: list[dict] = Field(min_length=1, max_length=3)
    frames: list[Frame] = Field(max_length=301)
    segments: list[Segment] = Field(max_length=3000)
    playback_file: str = Field(pattern=r"^(playback\.mp4|track-\d+\.wav)$")
    playback_kind: Literal["audio", "video"]
    playback_frame_ms: list[int] = Field(max_length=36000)
    warnings: list[str] = Field(max_length=10)
    asr_status: Literal["ready", "partial", "not_applicable"]


def validate_manifest(value, directory: Path):
    try:
        m = Manifest.model_validate(value)
        assert m.profile == PROFILE and m.configuration == CONFIG
        assert 0 < m.end_ms - m.origin_ms <= CONFIG["max_duration_ms"]
        files = {m.playback_file}
        indexes = {f"{t['kind']}:{t['index']}" for t in m.tracks}
        for track in m.tracks:
            assert m.origin_ms <= track["start_ms"] < track["end_ms"] <= m.end_ms
            if track["kind"] == "audio":
                files.add(track["canonical_file"])
            timing = track["timing"]
            assert 0 < len(timing) <= CONFIG["max_decoded_frames"]
            for entry in timing:
                assert (
                    abs(
                        entry["pts"]
                        * entry["time_base"][0]
                        / entry["time_base"][1]
                        * 1000
                        - entry["original_ms"]
                    )
                    <= 1
                )
        for frame in m.frames:
            assert m.origin_ms <= frame.original_ms < m.end_ms
            assert (
                abs(
                    frame.pts * frame.time_base[0] / frame.time_base[1] * 1000
                    - frame.original_ms
                )
                <= 1
            )
            files.add(frame.file)
        for segment in m.segments:
            assert (
                segment.track in indexes
                and m.origin_ms <= segment.start_ms < segment.end_ms <= m.end_ms
            )
            assert segment.representation != "video" or segment.frames
            assert segment.representation != "transcript" or segment.text
            for w in segment.words:
                assert segment.start_ms <= w.start_ms < w.end_ms <= segment.end_ms
            files.add(segment.file)
        for name in files:
            assert Path(name).name == name
            path = directory / name
            assert path.is_file() and not path.is_symlink()
        assert (
            sum((directory / f).stat().st_size for f in files)
            <= CONFIG["max_output_bytes"]
        )
        assert len(m.playback_frame_ms) == len(
            next((t["timing"] for t in m.tracks if t["kind"] == "video"), [])
        )
        if m.playback_kind == "video":
            original = next(t["timing"] for t in m.tracks if t["kind"] == "video")
            assert all(
                abs(p - (o["original_ms"] - m.origin_ms)) <= 50
                for p, o in zip(m.playback_frame_ms, original)
            )
        return m.model_dump(mode="json")
    except Exception:
        raise InvalidFile("MEDIA_MANIFEST_INVALID") from None
