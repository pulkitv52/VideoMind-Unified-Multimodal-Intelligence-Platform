from copy import deepcopy
from uuid import uuid4
import pytest
from pydantic import ValidationError
from videomind.retrieval.config import POLICY, configuration
from videomind.retrieval.contracts import SearchRequest
from videomind.retrieval.ranking import fuse, overlap


def row(start=0, end=100, asset="a", rep="video"):
    return dict(
        id=uuid4(),
        asset_id=asset,
        revision_id="r",
        representation=rep,
        citations=[dict(locator_kind="temporal", start_ms=start, end_ms=end)],
    )


def test_duplicates_and_split_vectors_cast_one_vote_per_branch():
    a = row()
    b = row(rep="audio")
    c = row(200, 300, asset="b")
    branches = {
        "dense": [
            dict(id=a["id"], score=0.9),
            dict(id=a["id"], score=0.89),
            dict(id=b["id"], score=0.8),
            dict(id=c["id"], score=0.7),
        ],
        "lexical": [dict(id=b["id"], score=1)],
    }
    result = fuse(branches, [a, b, c], POLICY)
    assert len(result) == 2
    assert result[0]["fusion_score"] == pytest.approx(2 / 61)
    assert result[1]["branches"]["dense"]["rank"] == 2
    assert len(result[0]["members"]) == 2


def test_grouping_does_not_chain_across_whole_timeline():
    a = row(0, 100)
    b = row(25, 125)
    c = row(50, 150)
    assert overlap(a, b) and overlap(b, c) and not overlap(a, c)
    result = fuse(
        {"dense": [dict(id=r["id"], score=0.8) for r in (a, b, c)]}, [a, b, c], POLICY
    )
    assert 1 <= len(result) <= 2
    for group in result:
        assert all(overlap(group["members"][0], r) for r in group["members"])


def test_abstention_and_native_evidence_survives_lexical_ranking():
    native = row(rep="audio")
    text = row(asset="b", rep="text")
    weak = row(asset="c")
    result = fuse(
        {
            "dense": [dict(id=native["id"], score=0.8), dict(id=weak["id"], score=0.1)],
            "lexical": [dict(id=text["id"], score=2)],
        },
        [native, text, weak],
        POLICY,
    )
    assert {r["representation"] for r in result} == {"audio", "text"}
    assert fuse({"dense": [dict(id=weak["id"], score=0.1)]}, [weak], POLICY) == []


def test_diversity_and_single_asset_bypass():
    data = [row(n * 200, n * 200 + 100) for n in range(7)] + [row(asset="b")]
    branch = {"dense": [dict(id=r["id"], score=0.9) for r in data]}
    assert len(fuse(branch, data, POLICY)) == 4
    assert len(fuse(branch, data, POLICY, single_asset=True)) == 8


@pytest.mark.parametrize(
    "patch",
    [
        {"query": " "},
        {"query": "a" * 2001},
        {"top_k": 31},
        {"strategy": "unknown"},
        {"filters": {"source_ids": [str(uuid4()) for _ in range(51)]}},
        {"filters": {"media_interval": {"start_ms": 4, "end_ms": 3}}},
    ],
)
def test_request_bounds(patch):
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(dict(workspace_id=uuid4(), query="test") | patch)


def test_configuration_records_experiment():
    a = SearchRequest(workspace_id=uuid4(), query="test")
    assert (
        configuration(a)[1]
        != configuration(a.model_copy(update={"strategy": "per_modality"}))[1]
    )


def test_weak_native_view_cannot_replace_qualifying_lexical_evidence():
    native = row(rep="audio")
    transcript = row(rep="transcript")
    result = fuse(
        {
            "dense": [dict(id=native["id"], score=0.6)],
            "lexical": [dict(id=transcript["id"], score=0.1)],
        },
        [native, transcript],
        POLICY,
    )
    assert len(result) == 1 and result[0]["representation"] == "transcript"
    assert "dense" not in result[0]["branches"]
    assert len(result[0]["members"]) == 1
