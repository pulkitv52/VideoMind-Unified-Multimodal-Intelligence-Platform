"""Development-only calibration gates; abstain when no tested policy qualifies."""

import hashlib
import json
from statistics import mean

from evaluation.action_temporal.inspection import (
    interval_overlap_range,
    validate_observations,
)
from evaluation.action_temporal.protocol import digest, evaluate_falls, write_frozen
from evaluation.quality.metrics import percentile

RECIPE_NAMES = ("current_native", "uniform12", "short4", "fine2")
# Adopted pilot targets, not thresholds fitted to these results.
GATES = {"asset_recall": 0.85, "adl_admission": 0.10, "temporal_recall_iou_050": 0.80}


def temporal_diagnostics(candidates, accepted, positive_assets, proposals):
    """Asset-capped result localization and an explicitly oracle, pre-filter ceiling."""
    rows = []
    for asset_id in sorted(positive_assets):
        events = proposals.get(asset_id, [])
        if len(events) != 1:
            raise ValueError(
                "Pilot requires exactly one provisional event per fall asset"
            )
        event = events[0]

        def overlap(row):
            return interval_overlap_range(
                row["interval"], event["start_range_ms"], event["end_range_ms"]
            )

        selected = next((r for r in accepted if r["asset_id"] == asset_id), None)
        raw = [r for r in candidates if r["asset_id"] == asset_id]
        bounds = overlap(selected) if selected else [0.0, 0.0]

        def error_range(point, feasible):
            return [
                max(feasible[0] - point, point - feasible[1], 0),
                max(abs(point - feasible[0]), abs(point - feasible[1])),
            ]

        rows.append(
            {
                "asset_id": asset_id,
                "accepted_interval": selected["interval"] if selected else None,
                "accepted_score": selected["score"] if selected else None,
                "iou_range": bounds,
                "absolute_start_error_ms_range": (
                    error_range(selected["interval"][0], event["start_range_ms"])
                    if selected
                    else None
                ),
                "absolute_end_error_ms_range": (
                    error_range(selected["interval"][1], event["end_range_ms"])
                    if selected
                    else None
                ),
                "oracle_any_window_conservative_iou": max(
                    (overlap(r)[0] for r in raw), default=0.0
                ),
                "oracle_any_window_optimistic_iou": max(
                    (overlap(r)[1] for r in raw), default=0.0
                ),
            }
        )
    if not rows:
        raise ValueError("Temporal cohort cannot be empty")
    errors = {}
    for kind in ("start", "end"):
        values = [
            r[f"absolute_{kind}_error_ms_range"]
            for r in rows
            if r[f"absolute_{kind}_error_ms_range"] is not None
        ]
        errors[kind] = {
            "accepted_events": len(values),
            "median_ms_range": [
                percentile([v[i] for v in values], 0.5) for i in (0, 1)
            ],
            "p90_ms_range": [percentile([v[i] for v in values], 0.9) for i in (0, 1)],
        }
    return {
        "boundary_errors_conditional_on_acceptance": errors,
        "events": len(rows),
        "per_event": rows,
        "conservative_recall": {
            str(t): mean(r["iou_range"][0] >= t for r in rows) for t in (0.3, 0.5, 0.7)
        },
        "optimistic_recall": {
            str(t): mean(r["iou_range"][1] >= t for r in rows) for t in (0.3, 0.5, 0.7)
        },
        "oracle_pre_acceptance_recall_at_050": mean(
            r["oracle_any_window_conservative_iou"] >= 0.5 for r in rows
        ),
        "scope": "One proposed event per positive asset. Oracle uses labels to pick a window and is never a retrieval result. Unaccepted events count as misses; boundary uncertainty is not a confidence interval.",
    }


def evaluate_configuration(queries, assets, observations, floor):
    cohort = [
        a
        for a in assets
        if a["split"] == "development" and a.get("sequence_class") in ("fall", "adl")
    ]
    allowed = {a["asset_id"] for a in cohort}
    positives = {a["asset_id"] for a in cohort if a["sequence_class"] == "fall"}
    proposals = {a["asset_id"]: a["fall_proposals"] for a in observations["assets"]}
    results = []
    for query in queries:
        if query["family"] != "fall":
            continue
        candidates = [
            r for r in query["development_candidates"] if r["asset_id"] in allowed
        ]
        metrics = evaluate_falls(candidates, cohort, floor)
        temporal = temporal_diagnostics(
            candidates, metrics["accepted"], positives, proposals
        )
        passed = (
            metrics["positive_asset_recall_at_10"] >= GATES["asset_recall"]
            and metrics["negative_asset_acceptance_rate"] <= GATES["adl_admission"]
            and temporal["conservative_recall"]["0.5"]
            >= GATES["temporal_recall_iou_050"]
        )
        metrics["accepted_positive_assets"] = sum(
            r["asset_id"] in positives for r in metrics["accepted"]
        )
        metrics["accepted_adl_assets"] = sum(
            r["asset_id"] not in positives for r in metrics["accepted"]
        )
        results.append(
            {
                "query_id": query["query_id"],
                "proxy_asset_metrics": metrics,
                "provisional_temporal_metrics": temporal,
                "pilot_gates_met": passed,
            }
        )
    if len(results) != 3 or len({r["query_id"] for r in results}) != 3:
        raise ValueError("Calibration requires all three frozen fall paraphrases")
    return {
        "floor": floor,
        "per_query": results,
        "pilot_gates_met_for_every_phrase": all(r["pilot_gates_met"] for r in results),
        "gold_eligible": False,
    }


def calibrate(root, protocol):
    if (
        digest({k: v for k, v in protocol.items() if k != "sha256"})
        != protocol["sha256"]
    ):
        raise ValueError("Protocol identity mismatch")
    observation_path = (
        root / "evaluation/annotations/action-temporal-v1-agent-observations.json"
    )
    observations = json.loads(observation_path.read_text())
    validate_observations(protocol, observations)
    report_dir = root / "evaluation/reports"
    paths = [observation_path, root / "evaluation/manifests/action-temporal-v1.json"]
    recipes = {}
    for name in RECIPE_NAMES:
        path = (
            report_dir
            / f"action-temporal-v1-{'baseline' if name == 'current_native' else name}.json"
        )
        data = json.loads(path.read_text())
        if data["protocol_sha256"] != protocol["sha256"]:
            raise ValueError("Score report identity mismatch")
        if name == "current_native":
            queries = [
                dict(q, development_candidates=q["candidates"]["native_video"])
                for q in data["rows"]
            ]
        else:
            if not data["complete"]:
                raise ValueError("Incomplete recipe")
            queries = data["queries"]
        recipes[name] = queries
        paths.append(path)
    # Freeze the procedure before computing this calibration report. Existing development
    # results were already inspected; this is not prospective preregistration.
    procedure = {
        "protocol_sha256": protocol["sha256"],
        "recipes": list(RECIPE_NAMES),
        "floors": protocol["floors"],
        "gates": GATES,
        "selection": "Every paraphrase must pass every pilot gate. If none pass, select no policy and do not score reserved groups. If several pass, choose fewer encoded windows, then higher floor, then recipe name. Human gold is separately required for promotion.",
        "cohort": "Three URFall development falls and three publisher ADL proxy negatives; three paraphrases of one family; not whole-platform retrieval or confirmed negative labels",
        "temporal": "Conservative overlap across uncertain agent boundary ranges; top-10, one highest-scoring accepted window per asset; unaccepted positives are temporal misses",
        "development_feedback": "User said everything looks fine about the review pack. Retained as development feedback, not independent annotations or resolved absence labels.",
        "provenance": "Post-hoc exploratory calibration on previously inspected development results",
        "gold_eligible": False,
        "inputs": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
    }
    procedure_path = root / "evaluation/manifests/action-temporal-calibration-v1.json"
    write_frozen(procedure_path, procedure)
    configurations = [
        {
            "recipe": name,
            **evaluate_configuration(queries, protocol["assets"], observations, floor),
        }
        for name, queries in recipes.items()
        for floor in protocol["floors"]
    ]
    passing = [c for c in configurations if c["pilot_gates_met_for_every_phrase"]]
    selected = None
    if passing:
        cohort_ids = {
            a["asset_id"]
            for a in protocol["assets"]
            if a["split"] == "development"
            and a.get("sequence_class") in ("fall", "adl")
        }
        costs = {
            name: len(
                {
                    (r["asset_id"], tuple(r["interval"]))
                    for q in recipes[name]
                    if q["family"] == "fall"
                    for r in q["development_candidates"]
                    if r["asset_id"] in cohort_ids
                }
            )
            for name in RECIPE_NAMES
        }
        winner = min(
            passing, key=lambda c: (costs[c["recipe"]], -c["floor"], c["recipe"])
        )
        selected = {"recipe": winner["recipe"], "floor": winner["floor"]}
    decision = {
        "procedure_sha256": digest(procedure),
        "selected_diagnostic_policy": selected,
        "promotion_authorized": False,
        "reserved_scoring_authorized_by_development_gate": selected is not None,
    }
    write_frozen(
        root / "evaluation/manifests/action-temporal-calibration-v1-decision.json",
        decision,
    )
    report = {
        **decision,
        "status": (
            "development_gates_failed"
            if not passing
            else "provisional_candidate_needs_validation"
        ),
        "configurations": configurations,
        "gold_eligible": False,
        "live_policy_changed": False,
        "reserved_quality_scored": False,
        "reserved_status": (
            "Withheld because no development setting passes"
            if not passing
            else "Pending separate frozen-policy evaluation; not automatically executed"
        ),
        "human_review": "19 records remain pending; user feedback does not supply two independent reviews",
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "evaluation/action_temporal/calibration.py",
                "evaluation/action_temporal/inspection.py",
                "evaluation/action_temporal/protocol.py",
                "evaluation/quality/metrics.py",
            )
        },
        "next_gate": "If all settings fail, investigate action/localization representation in a bounded AT2 CPU experiment. Do not tune on reserved data or lower release criteria.",
    }
    (report_dir / "action-temporal-v1-calibration.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report
