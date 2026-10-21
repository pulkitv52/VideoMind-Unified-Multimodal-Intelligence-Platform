"""Owned synthetic media, including variable presentation timestamps."""

import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave


def video(path, nonzero=False, speech=False):
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x120:rate=10:duration=3",
    ]
    if speech:
        args += ["-i", str(Path(__file__).parent / "fixtures/speech.wav"), "-shortest"]
    if nonzero:
        args += ["-vf", r"setpts=PTS+5/TB+if(gte(N\,15)\,0.3/TB\,0)", "-vsync", "vfr"]
    args += ["-c:v", "mpeg4", "-bf", "0", "-q:v", "4"]
    if speech:
        args += ["-c:a", "aac"]
    else:
        args += ["-an"]
    subprocess.run(args + ["-y", str(path)], check=True, timeout=20)
    return path


def audio(path, speech=False):
    if speech:
        shutil.copyfile(Path(__file__).parent / "fixtures/speech.wav", path)
    else:
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(
                b"".join(
                    struct.pack(
                        "<h", int(5000 * math.sin(2 * math.pi * 440 * i / 16000))
                    )
                    for i in range(48000)
                )
            )
    return path
