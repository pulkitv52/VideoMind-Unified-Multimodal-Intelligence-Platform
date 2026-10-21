"""Split ordered input units against a measured processor token budget."""

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def split_to_budget(
    units: Sequence[T], count_tokens: Callable[[Sequence[T]], int], budget: int = 7500
) -> list[Sequence[T]]:
    """Preserve order and every input unit; fail if an indivisible unit cannot fit.

    Units can be text tokens, timestamped frames, or audio sample blocks. The
    callback must count the actual processor output, including prompt overhead.
    Domain segmenters remain responsible for original-content locators.
    """
    if budget < 1:
        raise ValueError("budget must be positive")
    if len(units) == 0:
        return []
    count = count_tokens(units)
    if count < 0:
        raise ValueError("token count cannot be negative")
    if count <= budget:
        return [units]
    if len(units) == 1:
        raise ValueError("one input unit exceeds the processor budget")
    midpoint = len(units) // 2
    return split_to_budget(units[:midpoint], count_tokens, budget) + split_to_budget(
        units[midpoint:], count_tokens, budget
    )
