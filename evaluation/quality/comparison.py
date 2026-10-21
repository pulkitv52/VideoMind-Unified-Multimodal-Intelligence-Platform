"""Compare result content while ignoring request timing and neighbor display order."""

import copy
import math


def canonical(response):
    value = copy.deepcopy(response)
    for key in ("request_id", "timings_ms"):
        value.pop(key, None)
    for hit in value["results"]:
        hit["context"].sort(key=lambda item: item["segment_id"])
    return value


def equivalent(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            equivalent(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-7, abs_tol=1e-7)
    return left == right


def compare(before, after):
    if before["corpus_sha256"] != after["corpus_sha256"]:
        raise ValueError("Cannot compare different corpora")
    key = lambda row: (row["query_id"], row["mode"], row["strategy"])
    old = {key(row): row for row in before["rows"]}
    new = {key(row): row for row in after["rows"]}
    mismatches = [
        list(k)
        for k in sorted(old.keys() | new.keys())
        if k not in old
        or k not in new
        or not equivalent(canonical(old[k]["response"]), canonical(new[k]["response"]))
    ]
    return {
        "passed": not mismatches and len(old) == len(new) == 240,
        "requests_before": len(old),
        "requests_after": len(new),
        "mismatches": mismatches,
        "comparison": "Full ordered results, scores, citations, snippets, filters, facets and provenance; context sorted by segment ID; request ID and timings excluded; numeric tolerance 1e-7",
        "before_latency_ms": before["configuration_summaries"]["hybrid/unified"][
            "http_latency_ms"
        ],
        "after_latency_ms": after["configuration_summaries"]["hybrid/unified"][
            "http_latency_ms"
        ],
    }
