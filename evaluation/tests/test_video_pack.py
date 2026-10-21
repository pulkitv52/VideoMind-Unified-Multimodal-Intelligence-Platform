from fractions import Fraction
import io
import zipfile

import av
from PIL import Image
import pytest

from evaluation.datasets.video_pack import encode, rgb_frames, video_frames


def test_mp4_roundtrip_preserves_frame_time_mapping(tmp_path):
    positions = [0, 0.033, 0.071]
    frames = [
        (
            av.VideoFrame.from_image(Image.new("RGB", (64, 48), (n * 30, 0, 0))),
            position,
            {"source_frame": n},
        )
        for n, position in enumerate(positions)
    ]
    target = tmp_path / "sample.mp4"
    mapping = []
    assert encode(frames, target, Fraction(30), mapping) == 3
    decoded = list(video_frames(target))
    assert len(decoded) == 3
    assert [d[1] for d in decoded] == pytest.approx(positions, abs=0.001)
    assert [m["derivative_pts"] / 90000 for m in mapping] == pytest.approx(
        positions, abs=0.001
    )


def test_rgb_archive_uses_capture_timestamps_without_extracting_members(tmp_path):
    path = tmp_path / "frames.zip"
    annotation = tmp_path / "sync.csv"
    image = io.BytesIO()
    Image.new("RGB", (64, 48), "green").save(image, format="PNG")
    with zipfile.ZipFile(path, "w") as archive:
        for number in (1, 2, 3):
            archive.writestr(f"sequence/frame-{number:03d}.png", image.getvalue())
    annotation.write_text("1,100\n2,145\n3,200\n")
    frames = list(rgb_frames(path, annotation))
    assert [f[1] for f in frames] == pytest.approx([0, 0.045, 0.100])
    assert [f[2]["source_timestamp_ms"] for f in frames] == [100, 145, 200]
    assert not (tmp_path / "sequence").exists()


def test_nonmonotonic_frame_timestamps_fail_and_remove_partial_output(tmp_path):
    frame = av.VideoFrame.from_image(Image.new("RGB", (64, 48)))
    target = tmp_path / "sample.mp4"
    with pytest.raises(ValueError, match="Nonmonotonic"):
        encode([(frame, 0, {}), (frame, 0, {})], target, Fraction(30), [])
    assert not target.exists() and not target.with_suffix(".partial.mp4").exists()


def test_duplicate_source_pts_repairs_only_playback_and_keeps_original_locator(
    monkeypatch,
):
    from types import SimpleNamespace

    class Source:
        streams = SimpleNamespace(video=[object()])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def decode(self, stream):
            return iter(
                [
                    SimpleNamespace(pts=p, time_base=Fraction(1, 1000))
                    for p in (100, 140, 140, 180)
                ]
            )

    monkeypatch.setattr(av, "open", lambda path: Source())
    frames = list(video_frames("unused", repair_duplicates=True))
    assert [frame[2]["source_pts"] for frame in frames] == [100, 140, 140, 180]
    assert [frame[2]["playback_adjustment_ticks"] for frame in frames] == [0, 0, 1, 0]
    assert [round(frame[1] * 90000) for frame in frames] == [0, 3600, 3601, 7200]
