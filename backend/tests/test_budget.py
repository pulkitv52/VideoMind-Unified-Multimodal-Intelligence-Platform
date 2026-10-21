import pytest

from videomind.embeddings.budget import split_to_budget


def test_overflow_preserves_all_frames_and_order_with_prompt_overhead():
    frames = list(range(60))
    chunks = split_to_budget(frames, lambda chunk: len(chunk) * 140 + 10)
    assert len(chunks) > 1
    assert [frame for chunk in chunks for frame in chunk] == frames
    assert all(len(chunk) * 140 + 10 <= 7500 for chunk in chunks)


def test_indivisible_oversized_input_fails_instead_of_truncating():
    with pytest.raises(ValueError, match="one input unit"):
        split_to_budget(["oversized page"], lambda _: 8000)
