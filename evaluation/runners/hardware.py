import importlib.metadata
import platform
import ctypes
import gc
import shutil
import subprocess
from pathlib import Path


def memory_kib() -> dict[str, int]:
    result = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        result[key] = int(value.strip().split()[0])
    return result


def release_preprocessing_memory() -> dict:
    """Return freed Linux allocator arenas before applying the admission limit."""
    before = memory_kib()["MemAvailable"] / 1024**2
    gc.collect()
    allocator = ctypes.CDLL(None)
    trim = getattr(allocator, "malloc_trim", None)
    if trim is not None:
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        trim(0)
    return {
        "allocator_trim_available": trim is not None,
        "available_before_gib": before,
        "available_after_gib": memory_kib()["MemAvailable"] / 1024**2,
    }


def inventory() -> dict:
    import av
    import torch

    versions = {}
    for name in (
        "torch",
        "transformers",
        "sentence-transformers",
        "huggingface-hub",
        "pydantic",
        "numpy",
        "pillow",
        "av",
        "soundfile",
    ):
        versions[name] = importlib.metadata.version(name)
    tools = {}
    for name in ("ffmpeg", "tesseract", "libreoffice", "pdftoppm"):
        path = shutil.which(name)
        tools[name] = {"path": path}
        if path:
            probe = subprocess.run(
                [path, "--version" if name == "libreoffice" else "-v"],
                text=True,
                capture_output=True,
                timeout=10,
            )
            tools[name]["version_output"] = (probe.stdout + probe.stderr)[:1000]
    cpu = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        "unknown",
    )
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu,
        "logical_cpus": __import__("os").cpu_count(),
        "memory_kib": memory_kib(),
        "disk_free_bytes": shutil.disk_usage(".").free,
        "cuda_available": torch.cuda.is_available(),
        "torch_cpu_threads": torch.get_num_threads(),
        "gpus": [
            {
                "name": torch.cuda.get_device_name(i),
                "total_bytes": torch.cuda.get_device_properties(i).total_memory,
            }
            for i in range(torch.cuda.device_count())
        ],
        "packages": versions,
        "tools": tools,
        "pyav_linked_libraries": {k: list(v) for k, v in av.library_versions.items()},
    }
