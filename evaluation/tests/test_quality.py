import math
from pathlib import Path
import json
import pytest
from evaluation.quality.metrics import score, summarize, iou, percentile
from evaluation.quality.ablation import windows
from evaluation.quality.labels import intervals


def hit(asset, start=0, end=100):
    return {
        "asset": {"asset_id": asset},
        "citations": [
            {
                "anchor": {
                    "locator": {"kind": "temporal", "start_ms": start, "end_ms": end}
                }
            }
        ],
    }


def test_duplicate_windows_do_not_multiply_relevance_or_hide_display_rank():
    q = {
        "qrels": [{"asset_id": "a", "grade": 3}, {"asset_id": "b", "grade": 3}],
        "answerability": "positive",
    }
    result = score(q, [hit("a"), hit("a"), hit("b")])
    assert result["recall_at_10"] == 1
    expected = (7 + 7 / math.log2(4)) / (7 + 7 / math.log2(3))
    assert result["ndcg_at_10"] == pytest.approx(expected)


def test_temporal_overlap_and_correct_asset_both_required():
    q = {
        "qrels": [{"asset_id": "a", "grade": 3, "interval": [100, 200]}],
        "answerability": "positive",
    }
    assert score(q, [hit("b", 100, 200)])["temporal_recall_at_10"] == 0
    assert score(q, [hit("a", 0, 100)])["temporal_recall_at_10"] == 0
    assert score(q, [hit("a", 100, 200)])["temporal_recall_at_10"] == 1
    assert iou([0, 100], [50, 150]) == pytest.approx(1 / 3)


def test_negative_and_answerable_rejection_have_separate_denominators():
    assert score({"qrels": [], "answerability": "negative"}, [hit("a")])["false_useful"]
    assert score(
        {"qrels": [{"asset_id": "a", "grade": 3}], "answerability": "positive"}, []
    )["answerable_rejected"]
    assert score({"qrels": [], "answerability": "negative"}, [])["recall_at_10"] is None


def test_family_bootstrap_does_not_count_paraphrases_as_independent():
    metric = score(
        {"qrels": [{"asset_id": "a", "grade": 3}], "answerability": "positive"},
        [hit("a")],
    )
    rows = [{"family": "one", "metrics": metric} for _ in range(10)]
    result = summarize(rows)
    assert result["recall_at_10"]["families"] == 1
    assert result["recall_at_10"]["ci95"] == [1, 1]
    assert percentile([1, 3, 5], 0.5) == 3


def test_windows_have_bounded_overlap_and_positive_final_interval():
    assert list(windows(17480, {"window_ms": 12000, "overlap_ms": 2000})) == [
        (0, 12000),
        (10000, 17480),
    ]
    assert list(windows(3000, {"window_ms": 4000, "overlap_ms": 1000})) == [(0, 3000)]


def test_publisher_frames_use_mapping_instead_of_nominal_fps(tmp_path):
    xml = tmp_path / "labels.xml"
    xml.write_text(
        '<dataset><frame number="1"><hypothesis><context>fighting</context></hypothesis></frame><frame number="2"><hypothesis><context>fighting</context></hypothesis></frame></dataset>'
    )
    mapping = [
        {"source_frame": n, "derivative_pts": p, "derivative_time_base": "1/1000"}
        for n, p in enumerate((0, 150, 450, 800))
    ]
    assert intervals(xml, mapping, "fighting")[0]["interval"] == [150, 800]
    with pytest.raises(ValueError):
        intervals(xml, mapping[:2], "fighting")


def test_frozen_manifest_ids_and_provenance():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "evaluation/manifests/phase7-corpus.json").read_text()
    )
    qrels = json.loads((root / "evaluation/annotations/phase7-qrels.json").read_text())
    assert len({q["id"] for q in qrels["queries"]}) == len(qrels["queries"])
    assert not manifest["adjudicated"] and not manifest["human_reviewers"]
    assert qrels["corpus_sha256"] == manifest["sha256"]
    assert all(not q["human_reviewed"] for q in qrels["queries"])


def test_release_cannot_pass_with_synthetic_or_unreviewed_labels():
    from evaluation.quality.release import assess

    manifest = {
        "assets": [{"modality": "document"} for _ in range(200)],
        "adjudicated": True,
        "human_reviewers": ["one"],
    }
    qrels = {"queries": [{"human_reviewed": False} for _ in range(400)]}
    report = assess(manifest, qrels)
    assert report["status"] == "not_ready"
    assert not report["gates"]["independent_human_adjudication"]["passed"]
    assert not report["gates"]["scheduled_rpo"]["passed"]


def test_operator_bridges_are_syntax_checked_before_use():
    from evaluation.quality.bridge import BRIDGE
    from evaluation.quality.recovery import SNAPSHOT, RESTORE

    for source in (BRIDGE, SNAPSHOT, RESTORE):
        compile(source, "operator-bridge", "exec")


def test_invalid_windows_cannot_loop_forever():
    with pytest.raises(ValueError):
        list(windows(1000, {"window_ms": 100, "overlap_ms": 100}))


def test_required_evidence_sets_are_not_inferred_from_all_relevant_assets():
    q = {
        "qrels": [{"asset_id": "a", "grade": 3}, {"asset_id": "b", "grade": 2}],
        "answerability": "positive",
    }
    assert score(q, [hit("a")])["complete_set"] is None
    q["required_sets"] = [["a", "b"]]
    assert not score(q, [hit("a")])["complete_set"]
    assert score(q, [hit("a"), hit("b")])["complete_set"]


def test_result_comparison_preserves_rank_scores_and_citations():
    from evaluation.quality.comparison import canonical, equivalent
    import copy

    before = {
        "request_id": "old",
        "timings_ms": {"total": 100},
        "results": [
            {
                "segment_id": "match",
                "dense_score": 0.72,
                "citations": [{"id": "evidence"}],
                "context": [{"segment_id": "b"}, {"segment_id": "a"}],
            }
        ],
    }
    after = copy.deepcopy(before)
    after["request_id"] = "new"
    after["timings_ms"]["total"] = 50
    after["results"][0]["context"].reverse()
    assert equivalent(canonical(before), canonical(after))
    after["results"][0]["citations"][0]["id"] = "wrong"
    assert not equivalent(canonical(before), canonical(after))
    after = copy.deepcopy(before)
    after["results"][0]["dense_score"] = 0.73
    assert not equivalent(canonical(before), canonical(after))
