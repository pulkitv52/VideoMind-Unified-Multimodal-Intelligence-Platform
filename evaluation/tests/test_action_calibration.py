"""Calibration must fail closed on misses; known asset is not a localized event."""

import pytest

from evaluation.action_temporal.calibration import (
    evaluate_configuration,
    temporal_diagnostics,
)


def test_rejected_event_is_temporal_miss_even_when_raw_window_covers_it():
    rows = [{"asset_id": "fall", "interval": [1000, 2000], "score": 0.69}]
    proposals = {
        "fall": [{"start_range_ms": [1000, 1000], "end_range_ms": [2000, 2000]}]
    }
    result = temporal_diagnostics(rows, [], {"fall"}, proposals)
    assert result["conservative_recall"]["0.5"] == 0
    assert result["oracle_pre_acceptance_recall_at_050"] == 1
    assert (
        result["boundary_errors_conditional_on_acceptance"]["start"]["accepted_events"]
        == 0
    )
    assert result["boundary_errors_conditional_on_acceptance"]["start"][
        "median_ms_range"
    ] == [None, None]


def test_optimistic_uncertainty_cannot_rescue_conservative_gate():
    rows = [{"asset_id": "fall", "interval": [0, 2000], "score": 0.8}]
    proposals = {"fall": [{"start_range_ms": [0, 1000], "end_range_ms": [1500, 2000]}]}
    result = temporal_diagnostics(rows, rows, {"fall"}, proposals)
    assert result["optimistic_recall"]["0.5"] == 1
    assert result["conservative_recall"]["0.5"] == 0
    assert result["boundary_errors_conditional_on_acceptance"]["start"][
        "median_ms_range"
    ] == [0, 1000]


def test_correct_assets_wrong_intervals_fail_and_reserved_rows_are_excluded():
    assets = [
        {"asset_id": "positive", "split": "development", "sequence_class": "fall"},
        {"asset_id": "negative", "split": "development", "sequence_class": "adl"},
        {
            "asset_id": "reserved",
            "split": "reserved_diagnostic",
            "sequence_class": "adl",
        },
    ]
    observed = {
        "assets": [
            {
                "asset_id": "positive",
                "fall_proposals": [
                    {"start_range_ms": [0, 0], "end_range_ms": [1000, 1000]}
                ],
            }
        ]
    }
    queries = [
        {
            "query_id": f"fall-{i}",
            "family": "fall",
            "development_candidates": [
                {"asset_id": "positive", "interval": [2000, 3000], "score": 0.9},
                {"asset_id": "negative", "interval": [0, 1000], "score": 0.5},
                {"asset_id": "reserved", "interval": [0, 1000], "score": 1.0},
            ],
        }
        for i in range(1, 4)
    ]
    result = evaluate_configuration(queries, assets, observed, 0.7)
    assert not result["pilot_gates_met_for_every_phrase"]
    for row in result["per_query"]:
        assert row["proxy_asset_metrics"]["positive_asset_recall_at_10"] == 1
        assert row["proxy_asset_metrics"]["accepted_adl_assets"] == 0
        assert row["provisional_temporal_metrics"]["conservative_recall"]["0.5"] == 0
    for query in queries:
        query["development_candidates"][0]["interval"] = [0, 1000]
    assert evaluate_configuration(queries, assets, observed, 0.7)[
        "pilot_gates_met_for_every_phrase"
    ]
    queries.pop()
    with pytest.raises(ValueError, match="three"):
        evaluate_configuration(queries, assets, observed, 0.7)
