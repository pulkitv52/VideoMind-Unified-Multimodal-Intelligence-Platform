"""Generate small test assets locally; these are smoke inputs, not a benchmark."""

import ctypes
import ctypes.util
import hashlib
import importlib.metadata
import json
import math
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import resample_poly


def speech_samples(text: str) -> tuple[np.ndarray, int]:
    library = ctypes.util.find_library("espeak-ng")
    if not library:
        raise RuntimeError(
            "libespeak-ng is required to generate the local speech fixture"
        )
    engine = ctypes.CDLL(library)
    engine.espeak_Initialize.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    engine.espeak_Initialize.restype = ctypes.c_int
    rate = engine.espeak_Initialize(1, 0, None, 0)
    if rate <= 0:
        raise RuntimeError("eSpeak initialization failed")
    chunks = []
    callback_type = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
    )

    @callback_type
    def collect(samples, count, events):
        if samples and count > 0:
            chunks.append(np.ctypeslib.as_array(samples, shape=(count,)).copy())
        return 0

    engine.espeak_SetSynthCallback.argtypes = [callback_type]
    engine.espeak_SetSynthCallback(collect)
    engine.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    if engine.espeak_SetVoiceByName(b"en-us") != 0:
        raise RuntimeError("eSpeak English voice unavailable")
    engine.espeak_Synth.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    payload = ctypes.create_string_buffer(text.encode())
    if engine.espeak_Synth(payload, len(payload), 0, 0, 0, 1, None, None) != 0:
        raise RuntimeError("speech synthesis failed")
    engine.espeak_Synchronize()
    engine.espeak_Terminate()
    if not chunks:
        raise RuntimeError("speech synthesis returned no samples")
    divisor = math.gcd(rate, 16000)
    samples = np.concatenate(chunks).astype(np.float32) / 32768
    return (
        resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32),
        16000,
    )


def make_video(path: Path, frames: np.ndarray, speech: np.ndarray | None = None):
    with av.open(str(path), "w") as container:
        video = container.add_stream("mpeg4", rate=1)
        video.width = frames.shape[2]
        video.height = frames.shape[1]
        video.pix_fmt = "yuv420p"
        audio = container.add_stream("aac", rate=16000) if speech is not None else None
        for i, array in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, 1)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)
        if speech is not None:
            frame = av.AudioFrame.from_ndarray(
                speech[None, :], format="fltp", layout="mono"
            )
            frame.sample_rate = 16000
            frame.pts = 0
            frame.time_base = Fraction(1, 16000)
            for packet in audio.encode(frame):
                container.mux(packet)
            for packet in audio.encode():
                container.mux(packet)


def generate(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    passage = (
        "Emergency procedure: switch off the power before opening the safety panel."
    )
    (directory / "procedure.txt").write_text(passage + "\n")
    page = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(page)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    draw.text((30, 30), "EMERGENCY PROCEDURE", fill="black", font=font)
    draw.text((30, 110), "Switch off the power before", fill="black", font=font)
    draw.text((30, 150), "opening the safety panel.", fill="black", font=font)
    page.save(directory / "scanned-page.png")
    page.save(directory / "scanned-page.pdf")
    speech, rate = speech_samples(
        "Switch off the power before opening the safety panel."
    )
    sf.write(directory / "speech.wav", speech, rate, subtype="PCM_16")
    time = np.arange(rate * 3) / rate
    beep = (0.25 * np.sin(2 * np.pi * 880 * time) * ((time % 0.6) < 0.25)).astype(
        np.float32
    )
    sf.write(directory / "beeps.wav", beep, rate, subtype="PCM_16")
    frames = []
    for i in range(max(4, math.ceil(len(speech) / rate))):
        image = Image.new("RGB", (192, 128), "white")
        ImageDraw.Draw(image).rectangle((10 + 18 * i, 40, 45 + 18 * i, 75), fill="red")
        frames.append(np.array(image))
    frames = np.stack(frames)
    make_video(directory / "silent.mp4", frames)
    make_video(directory / "spoken.mp4", frames, speech)
    manifest = {
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("av", "numpy", "pillow", "scipy")
        },
        "provenance": "Locally generated synthetic fixtures; no user content",
        "speech_engine": "system libespeak-ng, en-us voice; record system version in report",
        "speech_text": "Switch off the power before opening the safety panel.",
        "files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir())
            if path.is_file() and path.name != "manifest.json"
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
