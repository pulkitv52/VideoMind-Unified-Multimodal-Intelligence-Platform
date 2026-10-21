import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
import av
import pytest
from PIL import Image
from evaluation.action_temporal.protocol import (
    evaluate_falls,
    EventReview,
    write_frozen,
)
from evaluation.action_temporal.windows import sample, run
from evaluation.quality.bridge import Encoder


def test_known_fall_is_admitted_without_treating_lower_floor_as_general_fix():
    assets = [
        {"asset_id": "fall", "split": "development", "sequence_class": "fall"},
        {"asset_id": "adl", "split": "development", "sequence_class": "adl"},
    ]
    rows = [
        {"asset_id": "fall", "score": 0.691237},
        {"asset_id": "adl", "score": 0.664069},
    ]
    high = evaluate_falls(rows, assets, 0.70)
    low = evaluate_falls(rows, assets, 0.65)
    assert high["positive_asset_recall_at_10"] == 0
    assert low["positive_asset_recall_at_10"] == 1
    assert low["negative_asset_acceptance_rate"] == 1
    assert low["temporal_recall"] is None and not low["gold_eligible"]


def test_duplicate_windows_and_reserved_labels_cannot_inflate_development_scores():
    assets = [
        {"asset_id": "positive", "split": "development", "sequence_class": "fall"},
        {"asset_id": "negative", "split": "development", "sequence_class": "adl"},
        {"asset_id": "negative2", "split": "development", "sequence_class": "adl"},
        {
            "asset_id": "reserved",
            "split": "reserved_diagnostic",
            "sequence_class": "fall",
        },
    ]
    rows = [
        {"asset_id": "positive", "score": 0.75},
        {"asset_id": "positive", "score": 0.76},
        {"asset_id": "negative", "score": 0.74},
        {"asset_id": "negative", "score": 0.73},
        {"asset_id": "reserved", "score": 0.99},
    ]
    score = evaluate_falls(rows, assets, 0.7)
    assert len(score["accepted"]) == 2
    assert score["negative_asset_acceptance_rate"] == 0.5
    assert score["positive_asset_recall_at_10"] == 1
    assert score["unjudged_excluded"] == 1


def test_reviews_reject_reversed_and_negative_original_time_intervals():
    value = {
        "reviewer": "review-1",
        "action": "fall",
        "start_ms": 100,
        "end_ms": 100,
        "provenance": "human",
        "visibility": "clear",
    }
    with pytest.raises(ValueError):
        EventReview(**value)
    value.update(start_ms=-1, end_ms=200)
    with pytest.raises(ValueError):
        EventReview(**value)


def test_protocol_is_idempotent_but_cannot_overwrite_changed_review_split(tmp_path):
    path = tmp_path / "protocol.json"
    write_frozen(path, {"split": "development"})
    write_frozen(path, {"split": "development"})
    with pytest.raises(ValueError):
        write_frozen(path, {"split": "reserved"})
    assert json.loads(path.read_text()) == {"split": "development"}


def test_sampling_uses_original_pts_instead_of_nominal_frame_number(tmp_path):
    path = tmp_path / "time.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width = 32
        stream.height = 32
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        stream.codec_context.max_b_frames = 0
        for pts in (0, 150, 450, 800, 1100):
            frame = av.VideoFrame.from_image(Image.new("RGB", (32, 32), "red"))
            frame.pts = pts
            frame.time_base = Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    assert [f["ms"] for f in sample(path)] == [0, 1100]


def test_batch_cannot_exceed_frozen_resource_limits(tmp_path):
    with pytest.raises(ValueError):
        run(tmp_path, {}, "short4", max_new=33)
    with pytest.raises(ValueError):
        run(tmp_path, {}, "short4", wall_seconds=1201)


def test_operator_encoder_stops_waiting_for_unresponsive_bridge(tmp_path):
    (tmp_path / ".local").mkdir(mode=0o700)
    encoder = Encoder(tmp_path, "x" * 64, response_timeout=0.05)
    encoder.process = subprocess.Popen(
        [sys.executable, "-c", "import sys,time;sys.stdin.readline();time.sleep(10)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        with pytest.raises(TimeoutError):
            encoder.encode("text", "query", True)
    finally:
        encoder.close()
    assert encoder.process.poll() is not None


def test_review_cannot_attach_an_interval_to_wrong_revision_or_past_media_end():
    from evaluation.action_temporal.assessment import review_status

    protocol = {
        "sha256": "frozen",
        "assets": [{"asset_id": "a", "revision_id": "r1", "duration_ms": 1000}],
    }
    review = {
        "protocol_sha256": "frozen",
        "independent_reviewers": [],
        "adjudicated": False,
        "assets": [
            {
                "asset_id": "a",
                "revision_id": "r2",
                "status": "needs_human_review",
                "events": [],
            }
        ],
    }
    with pytest.raises(ValueError, match="revision"):
        review_status(protocol, review)
    review["assets"][0]["revision_id"] = "r1"
    review["assets"][0]["events"] = [
        {
            "reviewer": "human-1",
            "action": "fall",
            "start_ms": 0,
            "end_ms": 1001,
            "provenance": "human",
            "visibility": "clear",
        }
    ]
    with pytest.raises(ValueError, match="outside"):
        review_status(protocol, review)
    review["assets"][0]["events"][0]["end_ms"] = 1000
    result = review_status(protocol, review)
    assert not result["gold_eligible"] and result["assets_needing_review"] == 1


def test_asset_ranking_penalizes_daily_activity_ahead_of_fall_even_at_full_recall():
    assets = [
        {"asset_id": "fall", "split": "development", "sequence_class": "fall"},
        {"asset_id": "adl", "split": "development", "sequence_class": "adl"},
    ]
    metric = evaluate_falls(
        [{"asset_id": "adl", "score": 0.8}, {"asset_id": "fall", "score": 0.75}],
        assets,
        0.7,
    )
    assert metric["positive_asset_recall_at_10"] == 1
    assert metric["ndcg_at_10"] == pytest.approx(0.6309297535714574)


def test_localization_distinguishes_matching_video_from_matching_event():
    from evaluation.action_temporal.inspection import interval_overlap_range

    # The accepted CAVIAR result starts after the proposed descent.
    assert interval_overlap_range([30000, 40560], [25920, 26400], [27840, 28320]) == [
        0,
        0,
    ]
    low, high = interval_overlap_range([1000, 3000], [266, 533], [1868, 2135])
    assert 0 < low < high < 1
    # An interior prediction edge can maximize overlap, not just range corners.
    assert interval_overlap_range([5, 15], [0, 10], [12, 20])[1] == 1


def test_inspection_rejects_reserved_groups_and_changed_revisions():
    from copy import deepcopy
    from evaluation.action_temporal.inspection import validate_observations

    root = Path(__file__).resolve().parents[2]
    protocol = json.loads(
        (root / "evaluation/manifests/action-temporal-v1.json").read_text()
    )
    observations = json.loads(
        (
            root / "evaluation/annotations/action-temporal-v1-agent-observations.json"
        ).read_text()
    )
    validate_observations(protocol, observations)
    broken = deepcopy(observations)
    broken["assets"][0]["revision_id"] = "different"
    with pytest.raises(ValueError, match="identity"):
        validate_observations(protocol, broken)
    reserved = next(a for a in protocol["assets"] if a["split"] != "development")
    broken = deepcopy(observations)
    broken["assets"].append(reserved)
    with pytest.raises(ValueError, match="Reserved"):
        validate_observations(protocol, broken)
    broken = deepcopy(observations)
    broken["assets"].pop()
    with pytest.raises(ValueError, match="Missing"):
        validate_observations(protocol, broken)
    broken = deepcopy(observations)
    broken["gold_eligible"] = True
    with pytest.raises(ValueError, match="human gold"):
        validate_observations(protocol, broken)


def test_inspection_rejects_invalid_or_overlapping_boundary_ranges():
    from evaluation.action_temporal.inspection import interval_overlap_range

    for start, end in (([100, 50], [200, 300]), ([0, 200], [100, 300])):
        with pytest.raises(ValueError):
            interval_overlap_range([0, 300], start, end)


def test_inspection_checks_source_bytes_before_writing_aids(tmp_path):
    from evaluation.action_temporal.inspection import inspect
    from evaluation.action_temporal.protocol import digest

    root = Path(__file__).resolve().parents[2]
    original = json.loads(
        (root / "evaluation/manifests/action-temporal-v1.json").read_text()
    )
    observed = json.loads(
        (
            root / "evaluation/annotations/action-temporal-v1-agent-observations.json"
        ).read_text()
    )
    asset = next(
        a
        for a in original["assets"]
        if a["asset_id"] == observed["assets"][0]["asset_id"]
    )
    protocol = {"assets": [dict(asset, path="changed.mp4")]}
    protocol["sha256"] = digest(protocol)
    observed["assets"] = observed["assets"][:1]
    observed["protocol_sha256"] = protocol["sha256"]
    annotation = (
        tmp_path / "evaluation/annotations/action-temporal-v1-agent-observations.json"
    )
    annotation.parent.mkdir(parents=True)
    annotation.write_text(json.dumps(observed))
    (tmp_path / "changed.mp4").write_bytes(b"different original")
    with pytest.raises(ValueError, match="checksum"):
        inspect(tmp_path, protocol)
    assert not (tmp_path / "evaluation/reports").exists()
