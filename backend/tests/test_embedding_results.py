import copy
import pytest
from videomind.embeddings.contracts import validate_result


def result():
    return {
        "profile": "a" * 64,
        "units": 4,
        "parts": [
            {
                "start_unit": 0,
                "end_unit": 4,
                "tokens": 20,
                "vector": [1.0] + [0.0] * 767,
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    ["profile", "missing", "overlap", "budget", "nonfinite", "zero", "dimension"],
)
def test_rejects_incompatible_or_incomplete_result(change):
    r = result()
    if change == "profile":
        r["profile"] = "b" * 64
    elif change == "missing":
        r["units"] = 5
    elif change == "overlap":
        r["parts"][0]["start_unit"] = 1
    elif change == "budget":
        r["parts"][0]["tokens"] = 7501
    elif change == "nonfinite":
        r["parts"][0]["vector"][0] = float("nan")
    elif change == "zero":
        r["parts"][0]["vector"] = [0.0] * 768
    elif change == "dimension":
        r["parts"][0]["vector"].pop()
    with pytest.raises(ValueError):
        validate_result(r, "a" * 64)


def test_complete_partition_preserves_all_units():
    r = result()
    r["parts"][0]["end_unit"] = 2
    part = copy.deepcopy(r["parts"][0])
    part.update(start_unit=2, end_unit=4)
    r["parts"].append(part)
    validate_result(r, "a" * 64)


@pytest.mark.parametrize(
    "template",
    [
        "{query:1000000000}",
        "{query!r}",
        "{query.__class__}",
        "{query}{query}",
        "{unknown}",
        "{query} {title}",
    ],
)
def test_rejects_unbounded_or_ambiguous_prompt_substitution(template):
    from videomind.embeddings.contracts import EmbeddingProfile, validate_prompts

    p = EmbeddingProfile(
        model_revision="a" * 40,
        processor_revision="a" * 40,
        runtime_lock_sha256="b" * 64,
        input_adapter="test",
        preprocessing_hash="c" * 64,
        query_prompt=template,
    )
    with pytest.raises(ValueError):
        validate_prompts(p)
