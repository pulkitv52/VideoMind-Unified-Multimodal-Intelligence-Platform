"""Report proxy quality separately from human-reviewed temporal release evidence."""

import hashlib
import json
import platform
import av
import PIL
from statistics import mean
from datetime import datetime, timezone
from evaluation.action_temporal.protocol import EventReview, evaluate_falls


def review_status(protocol, review):
    if review["protocol_sha256"] != protocol["sha256"]:
        raise ValueError("Review protocol mismatch")
    assets = {a["asset_id"]: a for a in protocol["assets"]}
    if set(assets) != {a["asset_id"] for a in review["assets"]}:
        raise ValueError("Review asset coverage mismatch")
    for row in review["assets"]:
        asset = assets[row["asset_id"]]
        if row["revision_id"] != asset["revision_id"]:
            raise ValueError("Review revision mismatch")
        for event in row["events"]:
            parsed = EventReview(**event)
            if parsed.end_ms > asset["duration_ms"]:
                raise ValueError("Review extends outside immutable original")
    return {
        "independent_human_reviewers": len(set(review["independent_reviewers"])),
        "adjudicated": review["adjudicated"],
        "assets_needing_review": sum(
            a["status"] != "reviewed" for a in review["assets"]
        ),
        "gold_eligible": False,
        "scope": "Prepared worksheet; event and absence adjudication has not been implemented as an automatic gold promotion path",
    }


def assess(root, protocol):
    report_dir = root / "evaluation/reports"
    baseline = json.loads((report_dir / "action-temporal-v1-baseline.json").read_text())
    if baseline["protocol_sha256"] != protocol["sha256"]:
        raise ValueError("Baseline identity mismatch")
    review = json.loads(
        (root / "evaluation/annotations/action-temporal-v1-review.json").read_text()
    )
    status = review_status(protocol, review)
    configurations = []
    cases = []
    complete = []
    pending = []
    resources = []
    for recipe in ("current_native", "uniform12", "short4", "fine2"):
        if recipe == "current_native":
            queries = [
                {
                    "query_id": r["query_id"],
                    "family": r["family"],
                    "development_candidates": r["candidates"]["native_video"],
                }
                for r in baseline["rows"]
            ]
        else:
            path = report_dir / f"action-temporal-v1-{recipe}.json"
            if not path.exists():
                pending.append(recipe)
                continue
            data = json.loads(path.read_text())
            if data["protocol_sha256"] != protocol["sha256"]:
                raise ValueError("Recipe identity mismatch")
            if not data["complete"]:
                pending.append(recipe)
                continue
            complete.append(recipe)
            queries = data["queries"]
            resources.extend([{"recipe": recipe, **run} for run in data["runs"]])
        for floor in protocol["floors"]:
            rows = []
            for q in queries:
                if q["family"] != "fall":
                    continue
                metric = evaluate_falls(
                    q["development_candidates"], protocol["assets"], floor
                )
                rows.append({"query_id": q["query_id"], **metric})
            configurations.append(
                {
                    "recipe": recipe,
                    "floor": floor,
                    "scope": "One fall-query family, three paraphrases; 3 fall/3 ADL development assets; publisher sequence labels only",
                    "positive_asset_recall_mean": mean(
                        r["positive_asset_recall_at_10"] for r in rows
                    ),
                    "negative_asset_acceptance_mean": mean(
                        r["negative_asset_acceptance_rate"] for r in rows
                    ),
                    "asset_ndcg_mean": mean(r["ndcg_at_10"] for r in rows),
                    "per_query": rows,
                    "proxy_gate_met_for_every_phrase": all(
                        r["positive_asset_recall_at_10"] >= 0.85
                        and r["negative_asset_acceptance_rate"] <= 0.10
                        for r in rows
                    ),
                    "gold_eligible": False,
                }
            )
        for q in queries:
            best = max(
                (
                    r
                    for r in q["development_candidates"]
                    if r.get("asset_key") == "urfall-fall-04"
                    or r["title"] == "urfall-fall-04__derived.mp4"
                ),
                key=lambda r: r["score"],
                default=None,
            )
            if best and q["family"] == "fall":
                cases.append({"recipe": recipe, "query_id": q["query_id"], **best})
    passing = [
        {"recipe": r["recipe"], "floor": r["floor"]}
        for r in configurations
        if r["proxy_gate_met_for_every_phrase"]
    ]
    sources = [
        *sorted((root / "evaluation/action_temporal").glob("*.py")),
        root / "evaluation/quality/bridge.py",
        root / "evaluation/quality/ablation.py",
        root / "evaluation/quality/metrics.py",
        root / "evaluation/quality/labels.py",
        root / "evaluation/quality/resources.py",
        root / "backend/src/videomind/embeddings/runtime.py",
        root / "backend/src/videomind/embeddings/profile.py",
        root / "backend/src/videomind/retrieval/repository.py",
        root / "backend/src/videomind/retrieval/config.py",
        root / "scripts/evaluate_action_temporal.py",
        root / "evaluation/tests/test_action_temporal.py",
    ]
    inputs = [
        root / "evaluation/manifests/action-temporal-v1.json",
        root / "evaluation/manifests/video30.json",
        root / "evaluation/manifests/phase7-corpus.json",
        root / "evaluation/annotations/action-temporal-v1-review.json",
        report_dir / "action-temporal-v1-baseline.json",
        *[report_dir / f"action-temporal-v1-{r}.json" for r in complete],
    ]
    verification_path = report_dir / "action-temporal-v1-verification.json"
    verification = (
        json.loads(verification_path.read_text())
        if verification_path.exists()
        else None
    )
    if verification_path.exists():
        inputs.append(verification_path)
    inspection_path = report_dir / "action-temporal-v1-inspection.json"
    inspection = None
    if inspection_path.exists():
        data = json.loads(inspection_path.read_text())
        if data["protocol_sha256"] != protocol["sha256"] or data["gold_eligible"]:
            raise ValueError("Inspection identity/provenance mismatch")
        inspection = {
            "report": str(inspection_path.relative_to(root)),
            "provenance": data["provenance"],
            "gold_eligible": False,
            "scope": "Post-hoc development frame inspection and overlap sensitivity; does not complete human review or policy calibration",
        }
        inputs.extend(
            [
                inspection_path,
                root
                / "evaluation/annotations/action-temporal-v1-agent-observations.json",
            ]
        )
    result = {
        "verification": verification,
        "development_inspection": inspection,
        "status": "not_ready_for_promotion",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "scope": "AT0/AT1 exploratory development pilot; no independent gold or temporal boundary result",
        "uncertainty_note": "One fall-query family with three paraphrases and six development clips; no independent human labels or release confidence intervals. All scores/quality are diagnostic.",
        "protocol_sha256": protocol["sha256"],
        "review_status": status,
        "complete_recipes": complete,
        "incomplete_or_unrun_recipes": pending,
        "configurations": configurations,
        "demonstrated_fall04": cases,
        "proxy_candidates_only": passing,
        "temporal_metrics": {
            "measured": False,
            "reason": "No adjudicated event boundaries; publisher context intervals are not fall-onset labels",
        },
        "reserved_sequence_quality_evaluated": False,
        "reserved_assets_present_in_full_index_baseline": True,
        "reserved_limitation": "Baseline replays the existing full index, whose raw scores include these assets. They are excluded from development quality metrics and threshold selection; experimental window query scores are withheld. This is not an unseen actor/session test.",
        "runtime": {
            "python": platform.python_version(),
            "pyav": av.__version__,
            "pillow": PIL.__version__,
            "machine": platform.machine(),
            "cpu_scope": "Existing pinned private CPU FP32 model, two model CPUs; no new dependencies installed",
        },
        "published_vectors": 0,
        "live_policy_changed": False,
        "auxiliary_model_loaded": False,
        "resource_runs": resources,
        "next_gate": "Human interval/negative review before temporal claims or final policy selection; AT2 only after reviewing AT1 limitations",
        "source_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        "input_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs
        },
    }
    path = report_dir / "action-temporal-v1-assessment.json"
    path.write_text(json.dumps(result, indent=2))
    return result
