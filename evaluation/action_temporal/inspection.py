"""Offline review aids and interval diagnostics; never a human-gold promotion path."""

import hashlib
import itertools
import json
from pathlib import Path

import av
from PIL import Image, ImageDraw

from evaluation.action_temporal.protocol import digest
from evaluation.quality.metrics import iou


def interval_overlap_range(prediction, start_range, end_range):
    """IoU sensitivity to uncertain onset/offset, including prediction-edge extrema."""
    if not (0 <= start_range[0] <= start_range[1] < end_range[0] <= end_range[1]):
        raise ValueError("Invalid or overlapping boundary uncertainty")
    if not (0 <= prediction[0] < prediction[1]):
        raise ValueError("Invalid prediction interval")
    starts = {
        *start_range,
        *(x for x in prediction if start_range[0] <= x <= start_range[1]),
    }
    ends = {*end_range, *(x for x in prediction if end_range[0] <= x <= end_range[1])}
    overlaps = [iou(prediction, [s, e]) for s, e in itertools.product(starts, ends)]
    return [min(overlaps), max(overlaps)]


def validate_observations(protocol, observations):
    if observations["protocol_sha256"] != protocol["sha256"]:
        raise ValueError("Observation protocol mismatch")
    if (
        observations["provenance"] != "agent_observation"
        or observations["gold_eligible"]
    ):
        raise ValueError("Inspection cannot assert human gold")
    assets = {a["asset_id"]: a for a in protocol["assets"]}
    seen = set()
    for row in observations["assets"]:
        asset = assets[row["asset_id"]]
        if row["asset_id"] in seen:
            raise ValueError("Duplicate observation")
        seen.add(row["asset_id"])
        if asset["split"] != "development":
            raise ValueError("Reserved groups cannot enter development inspection")
        for field in ("revision_id", "sha256", "mapping_sha256"):
            if row[field] != asset[field]:
                raise ValueError("Observation input identity mismatch")
        for event in row["fall_proposals"]:
            interval_overlap_range(
                [0, asset["duration_ms"]],
                event["start_range_ms"],
                event["end_range_ms"],
            )
            if event["end_range_ms"][1] > asset["duration_ms"]:
                raise ValueError("Observation exceeds original duration")
    if seen != {a["asset_id"] for a in assets.values() if a["split"] == "development"}:
        raise ValueError("Missing development observation; unknowns must be explicit")


def _sheet(root, asset, output, step_ms, start_ms=0, end_ms=None):
    end_ms = asset["duration_ms"] if end_ms is None else end_ms
    frames = []
    next_ms = start_ms
    previous = -1
    with av.open(str(root / asset["path"])) as container:
        for count, frame in enumerate(container.decode(video=0), 1):
            if count > 36000 or frame.width * frame.height > 16000000:
                raise ValueError("Inspection decoder bound exceeded")
            if frame.pts is None or frame.time_base is None:
                raise ValueError("Inspection requires source PTS")
            ms = round(frame.pts * frame.time_base * 1000)
            if ms < previous:
                raise ValueError("Nonmonotonic source PTS")
            previous = ms
            if ms >= end_ms:
                break
            if ms < next_ms:
                continue
            preview = frame.to_image()
            preview.thumbnail((320, 240))
            frames.append((ms, frame.pts, str(frame.time_base), preview))
            if len(frames) > 180:
                raise ValueError("Inspection sheet bound exceeded")
            next_ms = ms + step_ms
    if not frames:
        raise ValueError("No review frames")
    sheet = Image.new("RGB", (1280, 40 + 270 * ((len(frames) + 3) // 4)), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (8, 8),
        asset["asset_key"] + " | source PTS | agent review aid, not gold",
        fill="black",
    )
    for n, (ms, _, _, preview) in enumerate(frames):
        x, y = n % 4 * 320, 40 + n // 4 * 270
        sheet.paste(preview, (x, y))
        draw.text((x + 8, y + 244), f"{ms} ms", fill="black")
    sheet.save(output, quality=90)
    return {
        "path": str(output.relative_to(root)),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "frames": [
            {"ms": ms, "pts": pts, "time_base": tb} for ms, pts, tb, _ in frames
        ],
        "sampling_step_ms": step_ms,
    }


def inspect(root: Path, protocol):
    """Build checksum-verified development-only aids and raw-score diagnostics offline."""
    unsigned = {k: v for k, v in protocol.items() if k != "sha256"}
    if digest(unsigned) != protocol["sha256"]:
        raise ValueError("Protocol identity changed")
    observation_path = (
        root / "evaluation/annotations/action-temporal-v1-agent-observations.json"
    )
    observations = json.loads(observation_path.read_text())
    validate_observations(protocol, observations)
    assets = {
        a["asset_id"]: a for a in protocol["assets"] if a["split"] == "development"
    }
    # Validate every source before writing any output. Reserved groups are untouched.
    for asset in assets.values():
        for path_field, hash_field in (
            ("path", "sha256"),
            ("mapping_path", "mapping_sha256"),
        ):
            if (
                hashlib.sha256((root / asset[path_field]).read_bytes()).hexdigest()
                != asset[hash_field]
            ):
                raise ValueError("Original/mapping checksum mismatch")
    review_path = root / "evaluation/annotations/action-temporal-v1-review.json"
    human_before = hashlib.sha256(review_path.read_bytes()).hexdigest()
    output = root / "evaluation/reports/action-temporal-review"
    output.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for asset_id, asset in assets.items():
        sheets[asset_id] = [
            _sheet(
                root,
                asset,
                output / (asset["asset_key"] + ".jpg"),
                250 if asset["asset_key"].startswith("urfall") else 1000,
            )
        ]
        if asset["asset_key"] == "caviar-Rest_FallOnFloor":
            sheets[asset_id].append(
                _sheet(
                    root,
                    asset,
                    output / "caviar-fall-transition.jpg",
                    240,
                    24000,
                    30000,
                )
            )
    report_dir = root / "evaluation/reports"
    baseline_path = report_dir / "action-temporal-v1-baseline.json"
    baseline = json.loads(baseline_path.read_text())
    inputs = [observation_path, baseline_path]
    recipes = {
        "current_native": [
            dict(q, development_candidates=q["candidates"]["native_video"])
            for q in baseline["rows"]
        ]
    }
    for recipe in ("uniform12", "short4", "fine2"):
        path = report_dir / f"action-temporal-v1-{recipe}.json"
        data = json.loads(path.read_text())
        if data["protocol_sha256"] != protocol["sha256"] or not data["complete"]:
            raise ValueError("Incomplete/mismatched score report")
        recipes[recipe] = data["queries"]
        inputs.append(path)
    if baseline["protocol_sha256"] != protocol["sha256"]:
        raise ValueError("Baseline identity mismatch")
    temporal, confusion = [], []
    for recipe, queries in recipes.items():
        lookups = {
            q["query_id"]: {
                (r["asset_id"], tuple(r["interval"])): r
                for r in q["development_candidates"]
            }
            for q in queries
        }
        for query in queries:
            if query["family"] != "fall":
                continue
            for observed in observations["assets"]:
                rows = [
                    r
                    for r in query["development_candidates"]
                    if r["asset_id"] == observed["asset_id"]
                ]
                best = max(rows, key=lambda r: r["score"], default=None)
                if best is None:
                    continue
                key = (best["asset_id"], tuple(best["interval"]))
                posture = [
                    lookups[q][key] | {"query_id": q}
                    for q in ("sit-1", "bend-1", "lie-1")
                    if key in lookups.get(q, {})
                ]
                strongest = max(posture, key=lambda r: r["score"], default=None)
                confusion.append(
                    {
                        "recipe": recipe,
                        "query_id": query["query_id"],
                        "asset_key": observed["asset_key"],
                        "interval": best["interval"],
                        "fall_score": best["score"],
                        "strongest_posture": strongest,
                        "fall_minus_posture": (
                            best["score"] - strongest["score"] if strongest else None
                        ),
                        "observation": observed["observation"],
                    }
                )
                for event in observed["fall_proposals"]:
                    temporal.append(
                        {
                            "recipe": recipe,
                            "query_id": query["query_id"],
                            "asset_key": observed["asset_key"],
                            "score": best["score"],
                            "predicted_interval": best["interval"],
                            "proposal": event,
                            "iou_sensitivity_range": interval_overlap_range(
                                best["interval"],
                                event["start_range_ms"],
                                event["end_range_ms"],
                            ),
                            "accepted_at_live_floor": best["score"] >= 0.70,
                        }
                    )
    human_after = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if human_before != human_after:
        raise ValueError("Human worksheet changed during inspection")
    report = {
        "protocol_sha256": protocol["sha256"],
        "provenance": "agent_observation",
        "gold_eligible": False,
        "policy_selected": False,
        "live_changed": False,
        "reserved_groups_inspected": False,
        "scope": "Post-hoc development diagnostics only; observed ranges are not independent human event labels. Missing candidates are absent coverage, not a successful localization. Posture score differences are not calibrated classifiers.",
        "human_worksheet_sha256": human_after,
        "sheets": sheets,
        "temporal_rows": temporal,
        "posture_comparisons": confusion,
        "input_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (report_dir / "action-temporal-v1-inspection.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    lines = [
        "# Action and temporal review pack",
        "",
        "Development observations only. These are agent proposals after seeing retrieval scores, not independent human gold. Four reserved sequences are excluded. Original media and source PTS are retained; contact sheets can miss motion between frames.",
        "",
        "Use the [human worksheet](../../annotations/action-temporal-v1-review.md) for independent review. This command does not fill or adjudicate it. Boundary proposals describe the transition toward the floor through first settled floor posture; later lying is separate.",
        "",
        "## Top-scored windows for `person falling`",
        "",
        "IoU ranges express sensitivity to proposed boundary uncertainty, not a statistical confidence interval. Scores are similarities, not probabilities. Missing recipe/asset combinations were not encoded in that experiment.",
        "",
        "| Recipe | Clip | Window (s) | Similarity | IoU range against agent proposal | Clears 0.70 |",
        "|---|---|---|---:|---|---|",
    ]
    for row in temporal:
        if row["query_id"] != "fall-1":
            continue
        start, end = row["predicted_interval"]
        low, high = row["iou_sensitivity_range"]
        lines.append(
            f"| {row['recipe']} | {row['asset_key']} | {start / 1000:.3f}–{end / 1000:.3f} | {row['score']:.6f} | {low:.3f}–{high:.3f} | {'yes' if row['accepted_at_live_floor'] else 'no'} |"
        )
    for observed in observations["assets"]:
        asset = assets[observed["asset_id"]]
        lines.extend(
            [
                "",
                f"## {asset['asset_key']}",
                "",
                observed["observation"],
                "",
                f"[Open retained original](../../../{asset['path']})",
                "",
            ]
        )
        for event in observed["fall_proposals"]:
            lines.extend(
                [
                    f"Proposed onset range: {event['start_range_ms']} ms; settled-floor range: {event['end_range_ms']} ms. Human review pending.",
                    "",
                ]
            )
        for sheet in sheets[asset["asset_id"]]:
            filename = Path(sheet["path"]).name
            lines.extend(
                [
                    f"[Open timestamped frames]({filename})",
                    "",
                    f"![Source-PTS review frames]({filename})",
                    "",
                ]
            )
    (output / "index.md").write_text("\n".join(lines) + "\n")
    return report
