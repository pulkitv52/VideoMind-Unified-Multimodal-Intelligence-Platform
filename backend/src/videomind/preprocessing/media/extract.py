"""Offline decoding and CPU ASR. All intervals use original presentation time."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import wave

import av
from PIL import Image, ImageChops, ImageStat

from .profile import CONFIG, PROFILE, ASR_FILES


class MediaError(ValueError):
    pass


def command(args, timeout=120):
    try:
        subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise MediaError("MEDIA_TIMEOUT") from None
    except (OSError, subprocess.CalledProcessError):
        raise MediaError("MEDIA_DECODE_FAILED") from None


def windows(start, end, size, overlap):
    while start < end:
        stop = min(end, start + size)
        yield start, stop
        if stop == end:
            break
        start = stop - overlap


def probe(path, directory):
    output = directory / "probe.json"
    with output.open("wb") as stream:
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            stdout=stream,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
    if output.stat().st_size > 1024**2:
        raise MediaError("MEDIA_TRACK_LIMIT")
    data = json.loads(output.read_text())
    streams = [
        s
        for s in data["streams"]
        if s["codec_type"] in ("video", "audio")
        and not s.get("disposition", {}).get("attached_pic")
    ]
    videos = [s for s in streams if s["codec_type"] == "video"]
    audios = [s for s in streams if s["codec_type"] == "audio"]
    if len(videos) > 1 or len(audios) > 2 or not streams:
        raise MediaError("MEDIA_TRACK_LIMIT")
    for s in videos:
        if s["width"] * s["height"] > CONFIG["max_pixels"]:
            raise MediaError("MEDIA_PIXEL_LIMIT")
    duration = float(data.get("format", {}).get("duration", 0))
    if (
        duration - max(0, float(data.get("format", {}).get("start_time", 0)))
        > CONFIG["max_duration_ms"] / 1000 + 1
    ):
        raise MediaError("MEDIA_DURATION_LIMIT")
    return streams


def scan_video(path, index, directory):
    sampled = []
    timeline = []
    last = None
    next_sample = None
    shot_marks = []
    prior = None
    last_exact = None
    with av.open(str(path)) as container:
        stream = container.streams[index]
        stream.thread_count = 1
        for frame in container.decode(stream):
            if frame.pts is None:
                raise MediaError("MEDIA_TIMESTAMP_MISSING")
            pts = int(round(float(frame.pts * frame.time_base) * 1000))
            exact = frame.pts * frame.time_base
            if pts < 0 or (last_exact is not None and exact <= last_exact):
                raise MediaError("MEDIA_TIMELINE_UNSUPPORTED")
            if frame.width * frame.height > CONFIG["max_pixels"]:
                raise MediaError("MEDIA_PIXEL_LIMIT")
            last = pts
            last_exact = exact
            timeline.append(
                {
                    "pts": frame.pts,
                    "time_base": [
                        frame.time_base.numerator,
                        frame.time_base.denominator,
                    ],
                    "original_ms": pts,
                }
            )
            if len(timeline) > CONFIG["max_decoded_frames"]:
                raise MediaError("MEDIA_FRAME_LIMIT")
            if pts - timeline[0]["original_ms"] > CONFIG["max_duration_ms"]:
                raise MediaError("MEDIA_DURATION_LIMIT")
            if next_sample is None or pts >= next_sample:
                image = frame.to_image()
                image.thumbnail((CONFIG["frame_width"], CONFIG["frame_width"]))
                filename = f"frame-{len(sampled)}.jpg"
                image.save(directory / filename, quality=85)
                small = image.convert("RGB").resize((32, 32))
                if prior is not None:
                    difference = sum(
                        ImageStat.Stat(ImageChops.difference(prior, small)).mean
                    ) / (3 * 255)
                    if difference >= CONFIG["shot_threshold"]:
                        shot_marks.append(pts)
                prior = small
                sampled.append(
                    {
                        "file": filename,
                        "original_ms": pts,
                        "pts": frame.pts,
                        "time_base": timeline[-1]["time_base"],
                    }
                )
                next_sample = pts + 1000
        if not timeline:
            raise MediaError("MEDIA_EMPTY_TRACK")
        step = (
            float(stream.time_base) * float(stream.duration) if stream.duration else 0
        )
        frame_step = 1000 / float(stream.average_rate) if stream.average_rate else 40
        end = max(
            last + max(1, round(frame_step)),
            round(
                float(stream.start_time or 0) * float(stream.time_base) * 1000
                + step * 1000
            ),
        )
    return sampled, timeline, shot_marks, end


def scan_audio(path, index):
    timing = []
    end = None
    start = None
    last = None
    with av.open(str(path)) as container:
        stream = container.streams[index]
        stream.thread_count = 1
        for frame in container.decode(stream):
            if frame.pts is None:
                raise MediaError("MEDIA_TIMESTAMP_MISSING")
            pts = round(float(frame.pts * frame.time_base) * 1000)
            if pts < 0 or (last is not None and pts < last):
                raise MediaError("MEDIA_TIMELINE_UNSUPPORTED")
            if start is None:
                start = pts
            last = pts
            end = pts + round(frame.samples / frame.sample_rate * 1000)
            if end - start > CONFIG["max_duration_ms"]:
                raise MediaError("MEDIA_DURATION_LIMIT")
            timing.append(
                {
                    "pts": frame.pts,
                    "time_base": [
                        frame.time_base.numerator,
                        frame.time_base.denominator,
                    ],
                    "original_ms": pts,
                    "samples": frame.samples,
                    "sample_rate": frame.sample_rate,
                }
            )
            if len(timing) > CONFIG["max_decoded_frames"]:
                raise MediaError("MEDIA_FRAME_LIMIT")
    if start is None:
        raise MediaError("MEDIA_EMPTY_TRACK")
    return start, end, timing


def checkpoint():
    model = Path("/models/asr")
    for name, expected in ASR_FILES.items():
        path = model / name
        if not path.is_file():
            raise MediaError("ASR_MODEL_UNAVAILABLE")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != expected:
            raise MediaError("ASR_MODEL_MISMATCH")
    return model


def check_budget(directory):
    size = sum(
        p.stat().st_size
        for p in directory.iterdir()
        if p.is_file() and p.name != "original"
    )
    if size > CONFIG["max_output_bytes"]:
        raise MediaError("MEDIA_OUTPUT_LIMIT")


def extract(path, directory):
    streams = probe(path, directory)
    tracks = []
    frames = []
    timeline = []
    shots = []
    starts = []
    ends = []
    for s in streams:
        if s["codec_type"] == "video":
            frames, timeline, shots, end = scan_video(path, s["index"], directory)
            start = timeline[0]["original_ms"]
        else:
            start, end, timing = scan_audio(path, s["index"])
        starts.append(start)
        ends.append(end)
        track = {
            "index": s["index"],
            "kind": s["codec_type"],
            "codec": s.get("codec_name"),
            "time_base": s["time_base"],
            "start_ms": start,
            "end_ms": end,
            "channels": s.get("channels"),
            "sample_rate": s.get("sample_rate"),
            "timing": timeline if s["codec_type"] == "video" else timing,
        }
        tracks.append(track)
    origin = min(starts)
    end = max(ends)
    if end - origin > CONFIG["max_duration_ms"]:
        raise MediaError("MEDIA_DURATION_LIMIT")
    result = {
        "profile": PROFILE,
        "configuration": CONFIG,
        "origin_ms": origin,
        "end_ms": end,
        "tracks": tracks,
        "frames": frames,
        "segments": [],
        "playback_file": None,
        "playback_kind": "video" if frames else "audio",
        "warnings": [],
        "asr_status": "not_applicable",
    }
    ordinal = 0
    if frames:
        boundaries = [
            tracks[next(i for i, t in enumerate(tracks) if t["kind"] == "video")][
                "start_ms"
            ]
        ]
        for t in shots:
            if t - boundaries[-1] >= 2000:
                boundaries.append(t)
        video_track = next(t for t in tracks if t["kind"] == "video")
        boundaries.append(video_track["end_ms"])
        for left, right in zip(boundaries, boundaries[1:]):
            for a, b in windows(left, right, CONFIG["window_ms"], CONFIG["overlap_ms"]):
                selected = [f for f in frames if a <= f["original_ms"] < b]
                if not selected:
                    selected = [min(frames, key=lambda f: abs(f["original_ms"] - a))]
                name = f"visual-{ordinal}.json"
                (directory / name).write_text(
                    json.dumps(
                        {
                            "frames": selected,
                            "start_ms": a,
                            "end_ms": b,
                            "track": video_track["index"],
                        }
                    )
                )
                result["segments"].append(
                    {
                        "representation": "video",
                        "track": f"video:{video_track['index']}",
                        "start_ms": a,
                        "end_ms": b,
                        "file": name,
                        "frames": selected,
                        "text": None,
                        "words": [],
                    }
                )
                ordinal += 1
    asr = None
    audios = [t for t in tracks if t["kind"] == "audio"]
    for track in audios:
        idx = track["index"]
        name = f"track-{idx}.wav"
        wav = directory / name
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-threads",
                "1",
                "-copyts",
                "-i",
                str(path),
                "-map",
                f"0:{idx}",
                "-af",
                f"asetpts=PTS-{origin}/1000/TB,aresample=16000:async=1:first_pts=0",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(wav),
            ]
        )
        with wave.open(str(wav), "rb") as source:
            count = source.getnframes()
            rate = source.getframerate()
            actual_end = origin + round(count / rate * 1000)
            if abs(actual_end - track["end_ms"]) > 500:
                raise MediaError("MEDIA_ALIGNMENT_FAILED")
            track["canonical_file"] = name
            track["canonical_rate"] = rate
            track["canonical_samples"] = count
            track["canonical_origin_ms"] = origin
            for n, (a, b) in enumerate(
                windows(
                    origin, actual_end, CONFIG["audio_window_ms"], CONFIG["overlap_ms"]
                )
            ):
                target = f"audio-{idx}-{n}.wav"
                first = round((a - origin) * rate / 1000)
                stop = min(count, round((b - origin) * rate / 1000))
                source.setpos(first)
                with wave.open(str(directory / target), "wb") as output:
                    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(source.readframes(stop - first))
                result["segments"].append(
                    {
                        "representation": "audio",
                        "track": f"audio:{idx}",
                        "start_ms": a,
                        "end_ms": b,
                        "file": target,
                        "frames": [],
                        "text": None,
                        "words": [],
                    }
                )
        (directory / "progress.json").write_text(
            json.dumps(
                {"stage": "transcribe", "track": idx, "duration_ms": end - origin}
            )
        )
        try:
            if asr is None:
                from faster_whisper import WhisperModel

                asr = WhisperModel(
                    str(checkpoint()),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,
                    num_workers=1,
                    local_files_only=True,
                )
            utterances, info = asr.transcribe(
                str(wav),
                language="en",
                beam_size=1,
                word_timestamps=True,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            for u in utterances:
                a = max(origin, origin + round(u.start * 1000))
                b = min(actual_end, origin + round(u.end * 1000))
                if b <= a or not u.text.strip():
                    continue
                words = [
                    {
                        "word": w.word,
                        "start_ms": max(a, origin + round(w.start * 1000)),
                        "end_ms": min(b, origin + round(w.end * 1000)),
                    }
                    for w in u.words or []
                ]
                words = [w for w in words if w["end_ms"] > w["start_ms"]]
                result["segments"].append(
                    {
                        "representation": "transcript",
                        "track": f"audio:{idx}",
                        "start_ms": a,
                        "end_ms": b,
                        "file": name,
                        "frames": [],
                        "text": u.text.strip(),
                        "words": words,
                    }
                )
            result["asr_status"] = (
                "ready" if result["asr_status"] != "partial" else "partial"
            )
        except Exception:
            result["warnings"].append(f"ASR_FAILED_TRACK_{idx}")
            result["asr_status"] = "partial"
        check_budget(directory)
    if frames:
        video = next(t for t in tracks if t["kind"] == "video")
        args = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-copyts",
            "-i",
            str(path),
            "-map",
            f"0:{video['index']}",
        ]
        if audios:
            args += [
                "-map",
                f"0:{audios[0]['index']}",
                "-af",
                f"asetpts=PTS-{origin}/1000/TB,aresample=async=1:first_pts=0",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
            ]
        else:
            args += ["-an"]
        args += [
            "-vf",
            f"setpts=PTS-{origin}/1000/TB,scale='trunc(min({CONFIG['playback_width']},iw)/2)*2':-2,setsar=1",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-vsync",
            "vfr",
            "-enc_time_base",
            "-1",
            "-video_track_timescale",
            "1000000",
            "-g",
            "24",
            "-movflags",
            "+faststart",
            "-y",
            str(directory / "playback.mp4"),
        ]
        command(args)
        result["playback_file"] = "playback.mp4"
        # Verify the encoded presentation timestamps instead of assuming the muxer kept them.
        with av.open(str(directory / "playback.mp4")) as media:
            playback = [
                round(float(f.pts * f.time_base) * 1000) for f in media.decode(video=0)
            ]
        original = [p["original_ms"] - origin for p in timeline]
        if len(playback) != len(original) or any(
            abs(a - b) > 50 for a, b in zip(playback, original)
        ):
            raise MediaError("MEDIA_ALIGNMENT_FAILED")
        result["playback_frame_ms"] = playback
    else:
        result["playback_file"] = audios[0]["canonical_file"]
        result["playback_frame_ms"] = []
    check_budget(directory)
    return result


def main():
    directory = Path(sys.argv[1]).resolve()
    from videomind.preprocessing.sandbox import restrict

    try:
        restrict(
            directory,
            read_paths=("/models/asr",),
            memory_bytes=4 * 1024**3,
            cpu_seconds=600,
            file_bytes=128 * 1024**2,
        )
        result = extract(directory / "original", directory)
        (directory / "result.json").write_text(
            json.dumps({"ok": True, "manifest": result})
        )
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, MediaError)
            else (
                "SANDBOX_UNAVAILABLE"
                if str(exc) == "SANDBOX_UNAVAILABLE"
                else "MEDIA_DECODE_FAILED"
            )
        )
        (directory / "result.json").write_text(
            json.dumps({"ok": False, "error_code": code})
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
