"""Offline video sampling experiments. Never inserts vectors or changes generation."""

import base64
import hashlib
import io
import json
import math
import time
from fractions import Fraction
import av
from evaluation.quality.labels import checked
from evaluation.quality.metrics import iou
from evaluation.quality.bridge import Encoder

CONFIGS = [
    {"id": f"paired-4s-{fps}fps", "window_ms": 4000, "overlap_ms": 0, "fps": fps}
    for fps in (1, 2, 4)
]
KEYS = ("caviar-Fight_Chase", "caviar-Walk1", "urfall-fall-01", "urfall-adl-01")


def windows(duration, config):
    if duration <= 0 or not 0 <= config["overlap_ms"] < config["window_ms"]:
        raise ValueError("Invalid window bounds")
    start = 0
    while start < duration:
        end = min(duration, start + config["window_ms"])
        yield start, end
        if end == duration:
            break
        start += config["window_ms"] - config["overlap_ms"]


def sample(path, config):
    selected = []
    next_ms = 0
    interval = 1000 / config["fps"]
    last = 0
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        origin = None
        for frame in source.decode(stream):
            if origin is None:
                origin = frame.pts * frame.time_base
            ms = float((frame.pts * frame.time_base - origin) * 1000)
            last = ms
            if ms + 1e-6 < next_ms:
                continue
            image = frame.to_image()
            image.thumbnail((640, 640))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=82)
            selected.append((ms, base64.b64encode(buffer.getvalue()).decode()))
            while next_ms <= ms + 1e-6:
                next_ms += interval
        step = float(1000 / stream.average_rate) if stream.average_rate else 40
    return selected, math.ceil(last + step)


def run(root, manifest, qrels):
    encoder = Encoder(root, manifest["profile"])
    items = json.loads((root / "evaluation/manifests/video30.json").read_text())[
        "items"
    ]
    items = [r for r in items if r["id"] in KEYS]
    report = {
        "scope": "Four-asset paired diagnostic; fight window oracle-localized from publisher annotations, UR Fall first 4s with sequence labels only; not end-to-end retrieval or release gold",
        "corpus_sha256": manifest["sha256"],
        "profile": manifest["profile"],
        "configs": [],
    }
    query_vectors = {
        q["id"]: encoder.encode("text", q["query"], True)["parts"][0]["vector"]
        for q in qrels["queries"]
        if q["family"] in ("caviar-fight", "urfall-fall", "caviar-walk")
    }
    try:
        for config in CONFIGS:
            start_time = time.perf_counter()
            clips = []
            for item in items:
                path = checked(root, item["derivative"])
                frames, duration = sample(path, config)
                asset = next(a for a in manifest["assets"] if a["title"] == path.name)
                for start, end in (
                    [(12000, min(duration, 16000))]
                    if item["id"].startswith("caviar-")
                    else [(0, min(duration, 4000))]
                ):
                    frame_inputs = [
                        content for ms, content in frames if start <= ms < end
                    ]
                    if not frame_inputs:
                        raise ValueError("Empty sampled interval")
                    result = encoder.encode("video", frame_inputs)
                    if len(result["parts"]) != 1:
                        raise ValueError("Ablation requires unsplit windows")
                    clips.append(
                        {
                            "asset_id": asset["id"],
                            "title": asset["title"],
                            "asset_key": item["id"],
                            "interval": [start, end],
                            "sampled_frames": len(frame_inputs),
                            "vector": result["parts"][0]["vector"],
                        }
                    )
                print(f"{config['id']}: encoded {item['id']}", flush=True)
            results = []
            for query in qrels["queries"]:
                if query["id"] not in query_vectors:
                    continue
                vector = query_vectors[query["id"]]
                ranked = sorted(
                    [
                        dict(
                            clip,
                            score=sum(x * y for x, y in zip(vector, clip["vector"])),
                        )
                        for clip in clips
                    ],
                    key=lambda r: -r["score"],
                )
                relevant = {r["asset_id"]: r for r in query["qrels"]}
                seen = set()
                asset_ranked = []
                for hit in ranked:
                    if hit["asset_id"] not in seen:
                        asset_ranked.append(hit)
                        seen.add(hit["asset_id"])
                first = next(
                    (
                        n + 1
                        for n, h in enumerate(asset_ranked)
                        if h["asset_id"] in relevant
                    ),
                    None,
                )
                temporal = [g for g in relevant.values() if g.get("interval")]
                results.append(
                    {
                        "query_id": query["id"],
                        "family": query["family"],
                        "split": query["split"],
                        "first_relevant_asset_rank": first,
                        "accepted_relevant_at_10": any(
                            h["asset_id"] in relevant and h["score"] >= 0.7
                            for h in ranked[:10]
                        ),
                        "temporal_hit_at_10": (
                            any(
                                h["asset_id"] == g["asset_id"]
                                and iou(h["interval"], g["interval"]) >= 0.5
                                for h in ranked[:10]
                                for g in temporal
                            )
                            if temporal
                            else None
                        ),
                        "top5": [
                            {k: h[k] for k in ("title", "interval", "score")}
                            for h in asset_ranked[:5]
                        ],
                        "relevant_best": [
                            {
                                "title": h["title"],
                                "interval": h["interval"],
                                "score": h["score"],
                            }
                            for h in asset_ranked
                            if h["asset_id"] in relevant
                        ],
                    }
                )
            report["configs"].append(
                {
                    "configuration": config,
                    "windows": len(clips),
                    "frames": sum(c["sampled_frames"] for c in clips),
                    "seconds": time.perf_counter() - start_time,
                    "queries": results,
                }
            )
            (root / "evaluation/reports/phase7-ablation.json").write_text(
                json.dumps(report, indent=2)
            )
    finally:
        encoder.close()
    return report
