"""Real decoding, native sound retention, CPU ASR and PTS alignment checks."""

from pathlib import Path
import shutil
import wave
import pytest
from media_fixtures import audio, video
from videomind.evidence.media_routes import byte_range
from videomind.preprocessing.media.worker import run_extractor
from videomind.preprocessing.media.profile import CONFIG
from videomind.connectors.upload.validation import InvalidFile

runtime = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not Path("/models/asr/model.bin").exists(),
    reason="Compose media runtime required",
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, (0, 99, False)),
        ("bytes=0-9", (0, 9, True)),
        ("bytes=20-", (20, 99, True)),
        ("bytes=-10", (90, 99, True)),
        ("bytes=90-200", (90, 99, True)),
    ],
)
def test_single_ranges(value, expected):
    assert byte_range(value, 100) == expected


@pytest.mark.parametrize(
    "value",
    ["bytes=100-", "bytes=9-1", "bytes=-0", "bytes=0-1,4-5", "items=1-2", "bytes=-"],
)
def test_bad_ranges(value):
    with pytest.raises(ValueError):
        byte_range(value, 100)


@runtime
def test_silent_video_nonbrowser_codec_has_mapped_playback_and_frames(tmp_path):
    video(tmp_path / "original.mp4")
    (tmp_path / "original.mp4").rename(tmp_path / "original")
    manifest = run_extractor(tmp_path)
    assert (
        manifest["playback_kind"] == "video"
        and manifest["asr_status"] == "not_applicable"
    )
    assert any(s["representation"] == "video" for s in manifest["segments"])
    assert not any(s["representation"] == "audio" for s in manifest["segments"])
    assert manifest["frames"] and manifest["tracks"][0]["codec"] == "mpeg4"
    assert (tmp_path / "playback.mp4").exists()


@runtime
def test_nonzero_variable_frame_rate_preserves_each_presentation_time(tmp_path):
    video(tmp_path / "original.mp4", nonzero=True)
    (tmp_path / "original.mp4").rename(tmp_path / "original")
    m = run_extractor(tmp_path)
    assert m["origin_ms"] == 5000
    timing = m["tracks"][0]["timing"]
    gaps = {b["original_ms"] - a["original_ms"] for a, b in zip(timing, timing[1:])}
    assert len(gaps) > 1
    errors = [
        abs((t["original_ms"] - m["origin_ms"]) - p)
        for t, p in zip(timing, m["playback_frame_ms"])
    ]
    assert max(errors) <= 50 and len(timing) == len(m["playback_frame_ms"])


@runtime
def test_non_speech_sound_retained_across_full_timeline_even_without_transcript(
    tmp_path,
):
    audio(tmp_path / "original")
    m = run_extractor(tmp_path)
    clips = [s for s in m["segments"] if s["representation"] == "audio"]
    assert clips and clips[0]["start_ms"] == 0 and clips[-1]["end_ms"] == 3000
    with wave.open(str(tmp_path / clips[0]["file"]), "rb") as w:
        assert w.getnframes() == 48000 and w.getframerate() == 16000
    assert m["asr_status"] == "ready"


@runtime
@pytest.mark.parametrize("spoken_video", [False, True])
def test_real_pinned_asr_produces_word_evidence(spoken_video, tmp_path):
    if spoken_video:
        video(tmp_path / "original.mp4", speech=True)
        (tmp_path / "original.mp4").rename(tmp_path / "original")
    else:
        audio(tmp_path / "original", speech=True)
    m = run_extractor(tmp_path)
    assert m["asr_status"] == "ready", m["warnings"]
    transcript = [s for s in m["segments"] if s["representation"] == "transcript"]
    assert transcript
    assert "power" in " ".join(s["text"].lower() for s in transcript)
    for s in transcript:
        assert (
            s["words"] and m["origin_ms"] <= s["start_ms"] < s["end_ms"] <= m["end_ms"]
        )
        for word in s["words"]:
            assert s["start_ms"] <= word["start_ms"] < word["end_ms"] <= s["end_ms"]


@runtime
def test_media_wall_deadline_kills_parser_group(tmp_path, monkeypatch):
    audio(tmp_path / "original", speech=True)
    monkeypatch.setitem(CONFIG, "wall_seconds", 0.01)
    with pytest.raises(InvalidFile, match="MEDIA_TIMEOUT"):
        run_extractor(tmp_path)


@runtime
def test_duration_limit_is_checked_before_full_decoding(tmp_path, monkeypatch):
    from videomind.preprocessing.media.extract import extract, MediaError

    audio(tmp_path / "original")
    monkeypatch.setitem(CONFIG, "max_duration_ms", 1000)
    with pytest.raises(MediaError, match="MEDIA_DURATION_LIMIT"):
        extract(tmp_path / "original", tmp_path)


@runtime
def test_corrupt_media_has_stable_failure_code(tmp_path):
    (tmp_path / "original").write_bytes(b"not a media container")
    with pytest.raises(InvalidFile, match="MEDIA_DECODE_FAILED"):
        run_extractor(tmp_path)


@runtime
def test_asr_checkpoint_identity_is_verified(monkeypatch):
    from videomind.preprocessing.media.extract import checkpoint, MediaError
    from videomind.preprocessing.media.profile import ASR_FILES

    monkeypatch.setitem(ASR_FILES, "config.json", "0" * 64)
    with pytest.raises(MediaError, match="ASR_MODEL_MISMATCH"):
        checkpoint()


@runtime
def test_distinct_submillisecond_pts_are_not_rejected_as_duplicates(tmp_path):
    import subprocess

    target = tmp_path / "original.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10:duration=3",
            "-vf",
            "settb=1/90000,setpts='if(eq(N,15),PREV_OUTPTS+1,PTS)'",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-vsync",
            "vfr",
            "-enc_time_base",
            "1:90000",
            "-video_track_timescale",
            "90000",
            "-y",
            str(target),
        ],
        check=True,
        timeout=20,
    )
    target.rename(tmp_path / "original")
    m = run_extractor(tmp_path)
    timings = m["tracks"][0]["timing"]
    assert any(
        a["original_ms"] == b["original_ms"] and a["pts"] != b["pts"]
        for a, b in zip(timings, timings[1:])
    )
    assert len(timings) == len(m["playback_frame_ms"]) == 30


@runtime
def test_audio_video_offset_is_preserved_as_leading_canonical_silence(tmp_path):
    import subprocess
    import struct

    speech = Path(__file__).parent / "fixtures/speech.wav"
    target = tmp_path / "original.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10:duration=3",
            "-itsoffset",
            "0.3",
            "-i",
            str(speech),
            "-c:v",
            "mpeg4",
            "-bf",
            "0",
            "-c:a",
            "aac",
            "-y",
            str(target),
        ],
        check=True,
        timeout=20,
    )
    target.rename(tmp_path / "original")
    m = run_extractor(tmp_path)
    track = next(t for t in m["tracks"] if t["kind"] == "audio")
    assert 200 <= track["start_ms"] <= 350
    with wave.open(str(tmp_path / track["canonical_file"]), "rb") as wav:
        samples = wav.readframes(1600)
        assert max(abs(v[0]) for v in struct.iter_unpack("<h", samples)) == 0
    assert m["asr_status"] == "ready"


@runtime
def test_parent_rejects_changed_playback_mapping(tmp_path):
    from copy import deepcopy
    from videomind.preprocessing.media.contracts import validate_manifest

    video(tmp_path / "original.mp4")
    (tmp_path / "original.mp4").rename(tmp_path / "original")
    m = run_extractor(tmp_path)
    bad = deepcopy(m)
    bad["playback_frame_ms"][0] += 1000
    with pytest.raises(InvalidFile, match="MEDIA_MANIFEST_INVALID"):
        validate_manifest(bad, tmp_path)
