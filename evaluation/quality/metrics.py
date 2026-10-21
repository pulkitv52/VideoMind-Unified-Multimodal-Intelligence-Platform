"""Asset/family deduplication and explicit temporal and abstention denominators."""

import math
import random
from statistics import mean


def iou(left, right):
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0 else 0.0


def score(query, results, k=10):
    qrels = query["qrels"]
    relevant = {r["asset_id"]: r for r in qrels if r["grade"] > 0}
    unique = []
    seen = set()
    for hit in results[:k]:
        asset = hit["asset"]["asset_id"]
        if asset not in seen:
            unique.append(asset)
            seen.add(asset)
    recall = len(set(unique) & set(relevant)) / len(relevant) if relevant else None
    gains = []
    credited = set()
    for hit in results[:k]:
        asset = hit["asset"]["asset_id"]
        gains.append(
            relevant.get(asset, {}).get("grade", 0) if asset not in credited else 0
        )
        credited.add(asset)
    dcg = sum((2**g - 1) / math.log2(n + 2) for n, g in enumerate(gains))
    ideal = sum(
        (2**g - 1) / math.log2(n + 2)
        for n, g in enumerate(
            sorted((r["grade"] for r in relevant.values()), reverse=True)[:k]
        )
    )
    temporal = [r for r in qrels if r.get("interval")]
    matched = []
    for gold in temporal:
        locators = [
            c["anchor"]["locator"]
            for h in results[:k]
            if h["asset"]["asset_id"] == gold["asset_id"]
            for c in h["citations"]
        ]
        overlaps = [
            iou(gold["interval"], [l["start_ms"], l["end_ms"]])
            for l in locators
            if l["kind"] == "temporal"
        ]
        matched.append(max(overlaps, default=0) >= 0.5)
    return {
        "recall_at_10": recall,
        "ndcg_at_10": dcg / ideal if ideal else None,
        "temporal_recall_at_10": mean(matched) if matched else None,
        "false_useful": bool(results) if query["answerability"] == "negative" else None,
        "answerable_rejected": not results if relevant else None,
        "complete_set": (
            any(set(required).issubset(unique) for required in query["required_sets"])
            if query.get("required_sets")
            else None
        ),
    }


def summarize(rows, seed=701, bootstrap=1000):
    output = {}
    for metric in (
        "recall_at_10",
        "ndcg_at_10",
        "temporal_recall_at_10",
        "false_useful",
        "answerable_rejected",
        "complete_set",
    ):
        family = {}
        for row in rows:
            value = row["metrics"][metric]
            if value is not None:
                family.setdefault(row["family"], []).append(float(value))
        values = [mean(v) for v in family.values()]
        if not values:
            output[metric] = {"value": None, "families": 0}
            continue
        rng = random.Random(seed)
        samples = sorted(
            mean(rng.choices(values, k=len(values))) for _ in range(bootstrap)
        )
        output[metric] = {
            "value": mean(values),
            "families": len(values),
            "ci95": [
                samples[int(0.025 * bootstrap)],
                samples[min(bootstrap - 1, int(0.975 * bootstrap))],
            ],
        }
    return output


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
