"""Validate local OCR and ASR packaging without installing system packages."""

import ctypes
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def main():
    import av
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download

    report = {"ocr": {"status": "not_run"}, "asr": {"status": "not_run"}}
    directory = ROOT / "evaluation/fixtures/generated"
    tools = ROOT / ".cache/system-tools"
    try:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(tools / "usr/lib/x86_64-linux-gnu")
        env["TESSDATA_PREFIX"] = str(tools / "usr/share/tesseract-ocr/5/tessdata")
        binary = str(tools / "usr/bin/tesseract")
        version = subprocess.run(
            [binary, "--version"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        started = time.perf_counter()
        output = subprocess.run(
            [binary, str(directory / "scanned-page.png"), "stdout", "--psm", "6"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        report["ocr"] = {
            "status": "measured",
            "version": (version.stdout + version.stderr),
            "seconds": time.perf_counter() - started,
            "text": output.stdout,
            "sanity_passed": "switch off the power before opening the safety panel"
            in " ".join(re.findall(r"\w+", output.stdout.lower())),
        }
    except Exception as exc:
        report["ocr"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    report["deb_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / ".cache/system-debs").glob("*.deb"))
    }
    try:
        revisions = json.loads(
            (ROOT / "evaluation/manifests/model-revisions.json").read_text()
        )
        revision = revisions["Systran/faster-whisper-small.en"]["revision"]
        snapshot = snapshot_download(
            "Systran/faster-whisper-small.en", revision=revision, local_files_only=True
        )
        model = WhisperModel(
            snapshot, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1
        )
        started = time.perf_counter()
        segments, info = model.transcribe(
            str(directory / "speech.wav"),
            language="en",
            beam_size=1,
            vad_filter=False,
            word_timestamps=True,
        )
        rows = [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in s.words or []
                ],
            }
            for s in segments
        ]
        elapsed = time.perf_counter() - started
        text = " ".join(row["text"].strip() for row in rows)
        normalized = " ".join(re.findall(r"\w+", text.lower()))
        report["asr"] = {
            "status": "measured",
            "model_revision": revision,
            "faster_whisper": importlib.metadata.version("faster-whisper"),
            "ctranslate2": importlib.metadata.version("ctranslate2"),
            "compute_type": "int8",
            "seconds": elapsed,
            "duration_seconds": info.duration,
            "real_time_factor": elapsed / info.duration,
            "text": text,
            "segments": rows,
            "sanity_passed": normalized
            == "switch off the power before opening the safety panel",
            "valid_timestamps": bool(rows)
            and all(0 <= r["start"] < r["end"] <= info.duration + 0.1 for r in rows),
        }
    except Exception as exc:
        report["asr"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    report["pyav_version"] = av.__version__
    report["ffmpeg_version"] = av.ffmpeg_version_info
    # Inspect the actual bundled codec library rather than infer its license from codec names.
    for path in (Path(av.__file__).parent.parent / "av.libs").glob("libavcodec*.so*"):
        library = ctypes.CDLL(str(path))
        library.avcodec_license.restype = ctypes.c_char_p
        report["libavcodec_license"] = library.avcodec_license().decode()
    report["libreoffice"] = {"status": "not_installed", "validation": "pending"}
    output = ROOT / "evaluation/reports/auxiliary.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return (
        0
        if all(report[name].get("sanity_passed", False) for name in ("ocr", "asr"))
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
