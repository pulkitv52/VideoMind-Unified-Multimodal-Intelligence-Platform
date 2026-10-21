"""Fail-closed release assessment. Provisional labels cannot pass gold gates."""

from collections import Counter


def assess(
    manifest,
    qrels,
    search_report=None,
    recovery=None,
    verification=None,
    performance=None,
    comparison=None,
):
    queries = qrels["queries"]
    assets = manifest["assets"]
    reviewers = set(manifest.get("human_reviewers", []))
    gold = (
        manifest.get("adjudicated", False)
        and len(reviewers) >= 2
        and all(q.get("human_reviewed") for q in queries)
    )
    checks = {
        "corpus_size": {
            "passed": len(assets) >= 200,
            "observed": len(assets),
            "required": 200,
        },
        "query_count": {
            "passed": len(queries) >= 400,
            "observed": len(queries),
            "required": 400,
        },
        "independent_human_adjudication": {
            "passed": gold,
            "reviewers": len(reviewers),
            "required_reviewers": 2,
        },
        "per_class_coverage": {
            "passed": False,
            "observed_modalities": dict(Counter(a["modality"] for a in assets)),
            "required": "50 documents, 50 silent videos, 50 spoken videos, 50 standalone audio; video track classes require explicit review",
        },
    }
    if search_report:
        hybrid = search_report["configuration_summaries"]["hybrid/unified"]
        for name, target, direction in [
            ("recall_at_10", 0.85, "min"),
            ("ndcg_at_10", 0.70, "min"),
            ("temporal_recall_at_10", 0.80, "min"),
            ("false_useful", 0.10, "max"),
        ]:
            value = hybrid["overall"][name]["value"]
            numeric = value is not None and (
                value >= target if direction == "min" else value <= target
            )
            checks[name] = {
                "passed": gold and numeric,
                "provisional_observed": value,
                "target": target,
                "gold_eligible": gold,
                "numeric_target_met": numeric,
            }
        for slice_ in ("document", "silent_video", "spoken_video", "audio"):
            metrics = hybrid["slices"].get(slice_, {})
            strongest = []
            for mode in ("native_dense", "lexical", "derived_dense"):
                baseline = search_report["configuration_summaries"][mode + "/unified"][
                    "slices"
                ].get(slice_, {})
                value = baseline.get("ndcg_at_10", {}).get("value")
                if value is not None:
                    strongest.append(value)
            value = metrics.get("ndcg_at_10", {}).get("value")
            delta = value - max(strongest) if strongest and value is not None else None
            checks["hybrid_regression_" + slice_] = {
                "passed": gold and delta is not None and delta >= -0.02,
                "provisional_ndcg_delta": delta,
                "allowed_regression": 0.02,
            }
        latency = (
            performance["warm_success_latency_ms"]
            if performance
            else hybrid["http_latency_ms"]
        )
        checks["warm_latency"] = {
            "passed": bool(performance)
            and performance["warm_failed_requests"] == 0
            and latency["p95"] is not None
            and latency["p95"] <= 2000
            and latency["p99"] is not None
            and latency["p99"] <= 5000,
            "observed_ms": latency,
            "corpus_vectors": 197,
            "scope": "Dedicated 60-request serialized warm run when available; small corpus, not ingestion throughput or concurrent capacity",
        }
    checks["retrieval_change_equivalence"] = {
        "passed": bool(comparison and comparison.get("passed")),
        "comparison": comparison,
    }
    checks["isolated_restore"] = {
        "passed": bool(
            recovery
            and recovery.get("fixture_tombstone_replay", {}).get("runtime_isolation")
            and recovery.get("initial_restore", {}).get("runtime_isolation")
            and recovery.get("initial_restore", {}).get("http_citations", 0)
            == recovery.get("initial_restore", {})
            .get("counts", {})
            .get("citation_records", -1)
            and recovery.get("initial_restore", {}).get("http_citations", 0) > 0
            and recovery.get("fixture_tombstone_replay", {}).get(
                "probe_asset_memberships"
            )
            == 0
            and recovery.get("fixture_tombstone_replay", {}).get("dangling_citations")
            == 0
        )
    }
    checks["scheduled_rpo"] = {
        "passed": bool(recovery and recovery.get("scheduled_backups")),
        "required": "Scheduled backup policy and 24h RPO; manual drill alone insufficient",
    }
    checks["durable_tombstone_replay"] = {
        "passed": bool(recovery and recovery.get("durable_primary_tombstone_journal")),
        "required": "Durable post-backup deletion ledger surviving primary metadata retirement",
    }
    checks["security_and_lifecycle_regressions"] = {
        "passed": bool(
            verification
            and verification.get("failed") == 0
            and verification.get("passed", 0) > 0
            and verification.get("frontend_passed") is True
        ),
        "verification": verification,
    }
    for key in (
        "gold_citation_support",
        "filtered_ann_selectivity",
        "cold_and_ingestion_performance",
        "ingestion_throughput",
        "complete_evidence_set",
        "calibrated_answerable_rejection",
    ):
        checks[key] = {"passed": False, "status": "unmeasured_release_gate"}
    if performance:
        checks["cold_and_ingestion_performance"].update(
            status="partial_process_cold_measured_ingestion_unmeasured",
            process_cold=performance["cold"],
            os_file_cache_controlled=performance.get("os_file_cache_controlled", False),
        )
    return {
        "status": (
            "passed" if all(g["passed"] for g in checks.values()) else "not_ready"
        ),
        "scope": "Original Phase 7 release gates retained; no scope waiver inferred",
        "gates": checks,
        "failed_gates": [k for k, v in checks.items() if not v["passed"]],
    }
