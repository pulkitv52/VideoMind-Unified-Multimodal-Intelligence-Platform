"""Run from the repository root: python -m evaluation.runners.phase0 --help."""

import argparse
import hashlib
import json
import logging
import os
import resource
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from videomind.embeddings.budget import split_to_budget
from videomind.embeddings.contracts import EmbeddingProfile, validate_vector

from .fixtures import generate
from .hardware import inventory, memory_kib, release_preprocessing_memory

LOGGER = logging.getLogger(__name__)


def load_video(path):
    import av
    import numpy as np

    with av.open(str(path)) as container:
        tracks = [stream.type for stream in container.streams]
        frames = np.stack(
            [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
        )
    return frames, tracks


def load_audio(path):
    """Explicitly decode a soundtrack; passing video frames supplies no audio."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
    blocks = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            blocks.extend(
                out.to_ndarray().reshape(-1) for out in resampler.resample(frame)
            )
        blocks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    if not blocks:
        raise ValueError("soundtrack contains no decoded samples")
    return np.concatenate(blocks).astype(np.float32)


def processor_checks(processor, directory):
    import numpy as np
    import soundfile as sf
    from PIL import Image

    counts = {}
    arguments = {"return_tensors": "pt", "text_kwargs": {"truncation": False}}

    def count(**kwargs):
        features = processor(**kwargs, **arguments)
        return {
            "tokens": int(features["attention_mask"].sum()),
            "fields": sorted(features.keys()),
        }

    counts["document"] = count(text=(directory / "procedure.txt").read_text())
    with Image.open(directory / "scanned-page.png") as image:
        counts["scanned_page"] = count(images=image)
    frames, silent_tracks = load_video(directory / "silent.mp4")
    _, spoken_tracks = load_video(directory / "spoken.mp4")
    video_kwargs = {"do_sample_frames": False, "add_timestamps": False}
    counts["silent_video"] = count(videos=[frames], videos_kwargs=video_kwargs)
    counts["track_probe"] = {"silent": silent_tracks, "spoken": spoken_tracks}
    for name in ("speech", "beeps"):
        samples, rate = sf.read(directory / f"{name}.wav", dtype="float32")
        counts[name] = count(audio=samples, sampling_rate=rate)

    # Use actual expanded processor output to split a deliberately oversized video.
    # Disable the checkpoint's default 32-frame uniform sampling cap.
    oversized = np.stack([frames[i % len(frames)] for i in range(60)])
    measured = []

    def video_count(units):
        result = count(videos=[units], videos_kwargs=video_kwargs)["tokens"]
        measured.append({"frames": len(units), "tokens": result})
        return result

    chunks = split_to_budget(oversized, video_count)
    counts["overflow"] = {
        "input_frames": len(oversized),
        "output_frames": sum(len(chunk) for chunk in chunks),
        "chunks": [len(chunk) for chunk in chunks],
        "measurements": measured,
        "passed": sum(len(chunk) for chunk in chunks) == len(oversized)
        and len(chunks) > 1,
    }
    if not counts["overflow"]["passed"]:
        raise RuntimeError("oversized video did not split without dropping frames")
    return counts


def inference(profile, directory, device, repeats):
    import numpy as np
    import soundfile as sf
    import torch
    from PIL import Image
    from sentence_transformers import SentenceTransformer

    config = {}
    if "vision" not in profile.active_encoders:
        config["vision_config"] = None
    if "audio" not in profile.active_encoders:
        config["audio_config"] = None
    started = time.perf_counter()
    model = SentenceTransformer(
        profile.model_id,
        revision=profile.model_revision,
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        config_kwargs=config,
        model_kwargs={"torch_dtype": getattr(torch, profile.precision)},
    )
    load_seconds = time.perf_counter() - started
    model.eval()
    model[0].processing_kwargs = {
        "text": {"truncation": False},
        "video": {"do_sample_frames": False, "add_timestamps": False},
    }
    corpus = [
        "title: Safety procedure | text: Switch off the power before opening the safety panel.",
        "title: Cooking | text: Stir the tomato soup and serve with bread.",
    ]
    started = time.perf_counter()
    vectors = model.encode(
        corpus, normalize_embeddings=True, batch_size=2, show_progress_bar=False
    )
    batch_seconds = time.perf_counter() - started
    for vector in vectors:
        validate_vector(vector.tolist())
    query = "How do I safely open the electrical panel?"
    # A separate call warms query execution; timed repetitions follow it.
    model.encode(
        query,
        prompt_name="SearchQuery",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    durations = []
    for _ in range(repeats):
        if device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        query_vector = model.encode(
            query,
            prompt_name="SearchQuery",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if device == "cuda":
            torch.cuda.synchronize()
        durations.append(time.perf_counter() - started)
    validate_vector(query_vector.tolist())
    scores = vectors @ query_vector
    result = {
        "load_seconds": load_seconds,
        "text_batch_size": 2,
        "text_batch_seconds": batch_seconds,
        "text_items_per_second": 2 / batch_seconds,
        "warm_query_seconds": durations,
        "warm_query_median_seconds": statistics.median(durations),
        "text_scores": scores.tolist(),
        "text_sanity_passed": bool(scores[0] > scores[1]),
        "native_media": {},
    }
    indexed = {"document": vectors[0], "cooking_distractor": vectors[1]}
    inputs = []
    if "vision" in profile.active_encoders:
        inputs.append(
            (
                "scanned_page",
                {"image": Image.open(directory / "scanned-page.png")},
                query,
            )
        )
        spoken_frames, _ = load_video(directory / "spoken.mp4")
        inputs.append(
            (
                "spoken_video_visual",
                {"video": spoken_frames},
                "A red square moving across a white background",
            )
        )
        frames, _ = load_video(directory / "silent.mp4")
        inputs.append(
            (
                "silent_video",
                {"video": frames},
                "A red square moving across a white background",
            )
        )
    if "audio" in profile.active_encoders:
        for name, description in (
            ("speech", query),
            ("beeps", "Repeated electronic beeping tones"),
        ):
            samples, rate = sf.read(directory / f"{name}.wav", dtype="float32")
            inputs.append(
                (
                    name,
                    {"audio": {"array": samples, "sampling_rate": rate}},
                    description,
                )
            )
        samples = load_audio(directory / "spoken.mp4")
        inputs.append(
            (
                "spoken_video_audio",
                {"audio": {"array": samples, "sampling_rate": 16000}},
                query,
            )
        )
    for name, payload, description in inputs:
        LOGGER.info("Embedding native %s input", name)
        started = time.perf_counter()
        vector = model.encode(
            payload, normalize_embeddings=True, batch_size=1, show_progress_bar=False
        )
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        validate_vector(np.asarray(vector).reshape(-1).tolist())
        indexed[name] = np.asarray(vector).reshape(-1)
        descriptions = model.encode(
            [description, "A recipe for tomato soup"],
            prompt_name="SearchQuery",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        similarities = descriptions @ np.asarray(vector).reshape(-1)
        result["native_media"][name] = {
            "seconds": elapsed,
            "batch_size": 1,
            "items_per_second": 1 / elapsed,
            "scores": similarities.tolist(),
            "sanity_passed": bool(similarities[0] > similarities[1]),
        }
        if "audio" in payload:
            duration = len(payload["audio"]["array"]) / 16000
            result["native_media"][name].update(
                duration_seconds=duration, real_time_factor=elapsed / duration
            )
        if "video" in payload:
            result["native_media"][name]["frames_per_second"] = (
                len(payload["video"]) / elapsed
            )
    # This small dense-only corpus checks that one query can rank all native
    # views together. Broader relevance evaluation belongs to Phase 7.
    queries = {
        "safety": (query, {"document", "scanned_page", "speech", "spoken_video_audio"}),
        "visual": (
            "A red square moving across a white background",
            {"silent_video", "spoken_video_visual"},
        ),
        "sound": ("Repeated electronic beeping tones", {"beeps"}),
    }
    result["unified_retrieval"] = {}
    for name, (text, expected) in queries.items():
        relevant = expected & indexed.keys()
        if not relevant:
            continue
        encoded = model.encode(
            text,
            prompt_name="SearchQuery",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        ranking = sorted(
            ((key, float(value @ encoded)) for key, value in indexed.items()),
            key=lambda row: row[1],
            reverse=True,
        )
        result["unified_retrieval"][name] = {
            "ranking": [{"id": key, "cosine": score} for key, score in ranking],
            "expected_ids": sorted(relevant),
            "top1_relevant": ranking[0][0] in relevant,
        }
    result["peak_process_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if device == "cuda":
        result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--encoders", choices=["text", "vision", "audio", "all"], default="all"
    )
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--processor-only", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "evaluation/reports/phase0.json"
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete",
        "hardware": inventory(),
        "blockers": [],
        "gpu_validation": "not_run",
        "release_benchmark": False,
    }
    report["arguments"] = {
        "encoders": args.encoders,
        "device": args.device,
        "repeats": args.repeats,
    }
    report["source_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in (ROOT / "backend/src", ROOT / "evaluation/runners")
        for path in sorted(directory.rglob("*.py"))
    }
    revisions = json.loads(
        (ROOT / "evaluation/manifests/model-revisions.json").read_text()
    )
    revision = revisions["google/embeddinggemma-2"]["revision"]
    encoders = {
        "text": ("text",),
        "vision": ("text", "vision"),
        "audio": ("text", "audio"),
        "all": ("text", "vision", "audio"),
    }[args.encoders]
    profile = EmbeddingProfile(
        model_revision=revision,
        processor_revision=revision,
        runtime_lock_sha256=hashlib.sha256(
            (ROOT / "backend/uv.lock").read_bytes()
        ).hexdigest(),
        input_adapter="phase0-explicit-media-v1",
        preprocessing_hash=hashlib.sha256(
            (ROOT / "evaluation/runners/fixtures.py").read_bytes()
        ).hexdigest(),
        active_encoders=encoders,
    )
    report["profile"] = profile.model_dump()
    report["profile_sha256"] = profile.fingerprint
    directory = ROOT / "evaluation/fixtures/generated"
    try:
        if not (directory / "manifest.json").exists():
            generate(directory)
        report["fixtures"] = json.loads((directory / "manifest.json").read_text())
        for filename, checksum in report["fixtures"]["files"].items():
            if (
                hashlib.sha256((directory / filename).read_bytes()).hexdigest()
                != checksum
            ):
                raise ValueError(f"fixture checksum mismatch: {filename}")
        from transformers import AutoProcessor

        processor = AutoProcessor.from_pretrained(
            profile.model_id,
            revision=revision,
            local_files_only=True,
            trust_remote_code=False,
        )
        LOGGER.info("Checking actual processor token counts and media inputs")
        report["processor"] = processor_checks(processor, directory)
        del processor
        report["preprocessing_memory_release"] = release_preprocessing_memory()
        available_gib = memory_kib()["MemAvailable"] / 1024**2
        # Conservative admission estimates, not measured model memory requirements.
        minimum_gib = {"text": 2.0, "vision": 3.5, "audio": 4.5, "all": 6.0}[
            args.encoders
        ]
        report["memory_admission"] = {
            "available_gib": available_gib,
            "minimum_gib": minimum_gib,
        }
        if args.processor_only:
            report["blockers"].append(
                "Inference not requested; processor checks do not validate embeddings"
            )
        elif args.device == "cuda" and not report["hardware"]["cuda_available"]:
            report["blockers"].append("CUDA device unavailable")
        elif args.device == "cpu" and available_gib < minimum_gib:
            report["blockers"].append(
                f"CPU inference skipped: {available_gib:.2f} GiB available; conservative admission requires {minimum_gib} GiB"
            )
        else:
            LOGGER.info(
                "Loading pinned model with %s encoders on %s",
                args.encoders,
                args.device,
            )
            report["inference"] = inference(
                profile, directory, args.device, args.repeats
            )
            if args.device == "cuda":
                report["gpu_validation"] = "measured"
            passed = report["inference"]["text_sanity_passed"] and all(
                row["sanity_passed"]
                for row in report["inference"]["native_media"].values()
            )
            passed = passed and all(
                row["top1_relevant"]
                for row in report["inference"]["unified_retrieval"].values()
            )
            report["status"] = "smoke_passed" if passed else "smoke_failed"
            if args.encoders != "all":
                report["blockers"].append(
                    "Only selected encoders validated; full multimodal gate remains open"
                )
    except Exception as exc:
        LOGGER.exception("Feasibility check failed")
        report["blockers"].append(f"{type(exc).__name__}: {exc}")
        report["status"] = "error"
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        LOGGER.info("Report written to %s", args.report)
    return 0 if report["status"] == "smoke_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
