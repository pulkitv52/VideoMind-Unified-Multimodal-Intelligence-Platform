"""Whole-clip window ablations with resumable private vectors and bounded CPU work."""

import base64
import hashlib
import io
import json
from pathlib import Path
import time
import subprocess
import av
from evaluation.quality.ablation import windows
from evaluation.quality.bridge import Encoder
from evaluation.action_temporal.protocol import digest, evaluate_falls
from evaluation.quality.resources import mib
from videomind.embeddings.contracts import validate_result


def sample(path):
    frames = []
    next_ms = None
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        stream.thread_count = 1
        last = None
        for n, frame in enumerate(source.decode(stream)):
            if n >= 36000 or frame.pts is None or frame.width * frame.height > 16000000:
                raise ValueError("Decoder bounds")
            exact = frame.pts * frame.time_base
            if last is not None and exact <= last:
                raise ValueError("Non-monotonic source PTS")
            last = exact
            ms = round(exact * 1000)
            if next_ms is None or ms >= next_ms:
                image = frame.to_image()
                image.thumbnail((640, 640))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85)
                frames.append(
                    {
                        "ms": ms,
                        "pts": frame.pts,
                        "time_base": str(frame.time_base),
                        "content": base64.b64encode(buffer.getvalue()).decode(),
                    }
                )
                next_ms = ms + 1000
    if not frames or frames[0]["ms"] != 0:
        raise ValueError("Pilot expects the retained zero-origin derivatives")
    return frames


def cache_path(encoder, kind, content, query=False):
    payload = {
        "profile": encoder.profile,
        "kind": kind,
        "content": content,
        "query": query,
    }
    return encoder.cache / (
        hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        + ".json"
    )


def atomic(path, value, private=False):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2))
    if private:
        temp.chmod(0o600)
    temp.replace(path)


def snapshot():
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    services = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    services = [
        {k: row[k] for k in ("Name", "MemUsage", "CPUPerc")}
        for row in services
        if row["Name"].startswith("videomind-") and "-run-" not in row["Name"]
    ]
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        if name in ("MemAvailable", "SwapTotal", "SwapFree"):
            memory[name + "_kib"] = int(value.strip().split()[0])
    return {
        "services": services,
        "total_observed_mib": sum(mib(r["MemUsage"]) for r in services),
        "host": memory,
        "scope": "Coarse samples at batch start/end and every four completed windows; not true peak RSS or swap traffic",
    }


def run(root, protocol, recipe, max_new=32, wall_seconds=1200):
    if not 1 <= max_new <= 32 or not 1 <= wall_seconds <= 1200:
        raise ValueError("Batch bound exceeds adopted pilot envelope")
    config = protocol["recipes"][recipe]
    assets = [a for a in protocol["assets"] if a["asset_key"].startswith("urfall-")]
    expected = [
        (a, start, end)
        for a in assets
        for start, end in windows(a["duration_ms"], config)
    ]
    folder = root / ".local/action-temporal-v1"
    folder.mkdir(mode=0o700, exist_ok=True)
    checkpoint = folder / (recipe + ".json")
    state = {
        "protocol_sha256": protocol["sha256"],
        "recipe": recipe,
        "vectors": {},
        "runs": [],
    }
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
    if state["protocol_sha256"] != protocol["sha256"]:
        raise ValueError("Checkpoint protocol mismatch")
    # Revalidate even a fully cached resume against its immutable local inputs.
    for asset in assets:
        path = (root / asset["path"]).resolve()
        mapping = (root / asset["mapping_path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not mapping.is_relative_to(
            root.resolve()
        ):
            raise ValueError("Source/mapping path escaped root")
        if (
            hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]
            or hashlib.sha256(mapping.read_bytes()).hexdigest()
            != asset["mapping_sha256"]
        ):
            raise ValueError("Frozen source or mapping changed")
    encoder = Encoder(root, protocol["profile"])
    start_time = time.perf_counter()
    new = 0
    cache_hits = 0
    resources = [snapshot()]
    stop_reason = None
    query_vectors = {}
    try:
        for q in protocol["queries"]:
            query_vectors[q["id"]] = encoder.encode("text", q["text"], True)["parts"][
                0
            ]["vector"]
        sampled = {}
        for asset, start, end in expected:
            key = f"{asset['asset_id']}:{start}:{end}"
            if time.perf_counter() - start_time >= wall_seconds:
                stop_reason = "batch_wall_budget"
                break
            if resources[-1]["host"].get("MemAvailable_kib", 0) < 1048576:
                stop_reason = "host_memory_admission"
                break
            if asset["asset_id"] not in sampled:
                path = (root / asset["path"]).resolve()
                if (
                    not path.is_relative_to(root.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]
                ):
                    raise ValueError("Source hash/path changed")
                sampled[asset["asset_id"]] = sample(path)
            frames = [f for f in sampled[asset["asset_id"]] if start <= f["ms"] < end]
            if not frames:
                raise ValueError("Window has no supported sampled frame")
            payload = [f["content"] for f in frames]
            encoded_path = cache_path(encoder, "video", payload)
            if key in state["vectors"]:
                # Verify the exact profile/input cache, including legacy checkpoint rows.
                cached_result = json.loads(encoded_path.read_text())
                validate_result(cached_result, protocol["profile"])
                if (
                    cached_result["units"] != len(frames)
                    or len(cached_result["parts"]) != 1
                    or cached_result["parts"][0]["vector"]
                    != state["vectors"][key]["vector"]
                ):
                    raise ValueError(
                        "Cached checkpoint does not match its original input"
                    )
                recorded = state["vectors"][key].get("input_sha256", encoded_path.stem)
                if recorded != encoded_path.stem:
                    raise ValueError("Checkpoint input identity changed")
                state["vectors"][key]["input_sha256"] = encoded_path.stem
                continue
            cached = cache_path(encoder, "video", payload).exists()
            if not cached and new >= max_new:
                stop_reason = "batch_window_budget"
                break
            begun = time.perf_counter()
            result = encoder.encode("video", payload)
            if len(result["parts"]) != 1:
                raise ValueError(
                    "Pilot window unexpectedly split; cannot silently average"
                )
            new += not cached
            cache_hits += cached
            state["vectors"][key] = {
                "input_sha256": encoded_path.stem,
                "asset_id": asset["asset_id"],
                "asset_key": asset["asset_key"],
                "title": asset["title"],
                "interval": [start, end],
                "split": asset["split"],
                "frames": [
                    {k: v for k, v in f.items() if k != "content"} for f in frames
                ],
                "tokens": result["parts"][0]["tokens"],
                "vector": result["parts"][0]["vector"],
                "encode_seconds_observed": time.perf_counter() - begun,
                "cache_hit_on_first_record": cached,
            }
            atomic(checkpoint, state, private=True)
            if len(state["vectors"]) % 4 == 0:
                resources.append(snapshot())
            print(
                f"{recipe}: {len(state['vectors'])}/{len(expected)} windows ({new} new in batch)",
                flush=True,
            )
        resources.append(snapshot())
        elapsed = time.perf_counter() - start_time
        state["runs"].append(
            {
                "seconds": elapsed,
                "new_encodes": new,
                "cache_hits": cache_hits,
                "batch_max_new": max_new,
                "batch_wall_seconds": wall_seconds,
                "stop_reason": stop_reason,
                "resources": resources,
            }
        )
        atomic(checkpoint, state, private=True)
        public = [
            {k: v for k, v in r.items() if k != "vector"}
            for r in state["vectors"].values()
        ]
        evaluations = []
        for q in protocol["queries"]:
            vector = query_vectors[q["id"]]
            ranked = sorted(
                [
                    dict(
                        asset_id=r["asset_id"],
                        asset_key=r["asset_key"],
                        title=r["title"],
                        interval=r["interval"],
                        score=sum(
                            x * y for x, y in zip(vector, r["vector"], strict=True)
                        ),
                    )
                    for r in state["vectors"].values()
                    if r["split"] == "development"
                ],
                key=lambda r: (-r["score"], r["asset_id"], r["interval"]),
            )[:150]
            evaluations.append(
                {
                    "query_id": q["id"],
                    "family": q["family"],
                    "development_candidates": ranked,
                    "fall_floor_sweep": (
                        {
                            str(f): evaluate_falls(ranked, assets, f)
                            for f in protocol["floors"]
                        }
                        if q["family"] == "fall"
                        else None
                    ),
                }
            )
        complete = len(state["vectors"]) == len(expected)
        report = {
            "protocol_sha256": protocol["sha256"],
            "recipe": recipe,
            "input_recipe_sha256": digest(
                {"recipe": config, "preprocessing": protocol["preprocessing"]}
            ),
            "profile": protocol["profile"],
            "scope": "Ten complete UR Fall clips; development scoring only; one result per asset for provisional floor metrics; no production publication",
            "complete": complete,
            "metric_eligible": complete,
            "gold_eligible": False,
            "expected_windows": len(expected),
            "encoded_windows": len(public),
            "window_inputs": public,
            "runs": state["runs"],
            "queries": evaluations if complete else [],
            "partial_scores_withheld": not complete,
            "reserved_groups_scored": False,
            "temporal_metrics_status": "unmeasured: no adjudicated event boundaries",
            "active_model_unchanged": True,
            "published_vectors": 0,
        }
        atomic(
            root / "evaluation/reports" / f"action-temporal-v1-{recipe}.json", report
        )
        return report
    finally:
        encoder.close()
