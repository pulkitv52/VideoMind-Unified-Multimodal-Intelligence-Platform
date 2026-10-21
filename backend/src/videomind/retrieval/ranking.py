"""Evidence grouping precedes rank fusion. Native evidence keeps its own vote."""

from videomind.evidence.contracts import Citation, EvidenceAnchor
from videomind.contracts import AssetRef


def overlap(a, b, threshold=0.5):
    if (a["asset_id"], a["revision_id"]) != (b["asset_id"], b["revision_id"]):
        return False
    for x in a["citations"]:
        for y in b["citations"]:
            if x["locator_kind"] != y["locator_kind"]:
                continue
            kind = x["locator_kind"]
            if kind == "temporal":
                left, right = max(x["start_ms"], y["start_ms"]), min(
                    x["end_ms"], y["end_ms"]
                )
                union = max(x["end_ms"], y["end_ms"]) - min(
                    x["start_ms"], y["start_ms"]
                )
                if max(0, right - left) / union >= threshold:
                    return True
            elif kind == "text":
                if x["text_artifact_id"] != y["text_artifact_id"]:
                    continue
                intersection = max(
                    0,
                    min(x["end_char"], y["end_char"])
                    - max(x["start_char"], y["start_char"]),
                )
                union = max(x["end_char"], y["end_char"]) - min(
                    x["start_char"], y["start_char"]
                )
                if intersection / union >= threshold:
                    return True
            elif x["page"] == y["page"]:
                xb, yb = x["transform"].get("box"), y["transform"].get("box")
                if not xb or not yb:
                    if x["anchor_id"] == y["anchor_id"]:
                        return True
                    continue
                intersection = max(0, min(xb[2], yb[2]) - max(xb[0], yb[0])) * max(
                    0, min(xb[3], yb[3]) - max(xb[1], yb[1])
                )
                union = (
                    (xb[2] - xb[0]) * (xb[3] - xb[1])
                    + (yb[2] - yb[0]) * (yb[3] - yb[1])
                    - intersection
                )
                if union and intersection / union >= threshold:
                    return True
    return False


def fuse(branches, details, policy, top_k=10, single_asset=False):
    branches = {
        name: [
            r
            for r in rows
            if name != "dense" or r["score"] >= policy["minimum_dense_cosine"]
        ]
        for name, rows in branches.items()
    }
    participating = {r["id"] for rows in branches.values() for r in rows}
    details = [r for r in details if r["id"] in participating]
    by_id = {r["id"]: r for r in details}
    # Anchor a group to one deterministic representative; overlapping chains
    # cannot progressively swallow the entire media timeline.
    groups = []
    membership = {}
    for row in sorted(details, key=lambda r: str(r["id"])):
        group = next(
            (
                g
                for g in groups
                if overlap(g["members"][0], row, policy["group_overlap"])
            ),
            None,
        )
        if group is None:
            group = {"members": [], "branches": {}, "fusion_score": 0.0}
            groups.append(group)
        group["members"].append(row)
        membership[row["id"]] = group
    for name, candidates in branches.items():
        seen = set()
        rank = 0
        for candidate in candidates:
            group = membership.get(candidate["id"])
            if group is None or id(group) in seen:
                continue
            seen.add(id(group))
            rank += 1
            group["branches"][name] = {
                "rank": rank,
                "score": candidate["score"],
                "segment_id": candidate["id"],
            }
            group["fusion_score"] += 1 / (policy["rrf_k"] + rank)
    accepted = []
    for group in groups:
        branches = group["branches"]
        dense = branches.get("dense", {}).get("score", -1)
        if not branches or (
            not ("lexical" in branches or "identifier" in branches)
            and dense < policy["minimum_dense_cosine"]
        ):
            continue
        # Open the strongest matching representation, never an arbitrary neighbor.
        best = min(branches.items(), key=lambda item: (item[1]["rank"], item[0]))[1][
            "segment_id"
        ]
        primary = by_id[best]
        accepted.append(
            dict(
                primary,
                member_ids=[r["id"] for r in group["members"]],
                members=group["members"],
                branches=branches,
                fusion_score=group["fusion_score"],
            )
        )
    accepted.sort(key=lambda g: (-g["fusion_score"], str(g["id"])))
    selected = []
    counts = {}
    for group in accepted:
        asset = group["asset_id"]
        if (
            not single_asset
            and len(selected) < 10
            and counts.get(asset, 0) >= policy["asset_cap_first_ten"]
        ):
            continue
        selected.append(group)
        counts[asset] = counts.get(asset, 0) + 1
        if len(selected) == top_k:
            break
    return selected


def citations(row):
    asset = AssetRef(
        workspace_id=row["workspace_id"],
        source_id=row["source_id"],
        asset_id=row["asset_id"],
        revision_id=row["revision_id"],
    )
    values = []
    for item in row["citations"]:
        kind = item["locator_kind"]
        locator = {"kind": kind}
        fields = {
            "page": ("page",),
            "text": ("text_artifact_id", "start_char", "end_char"),
            "temporal": ("start_ms", "end_ms", "track"),
        }[kind]
        locator.update({f: item[f] for f in fields})
        if kind == "page":
            locator["box"] = item["transform"].get("box")
        values.append(
            Citation(
                id=item["id"],
                anchor=EvidenceAnchor(
                    id=item["anchor_id"],
                    asset=asset,
                    original_object_id=row["original_object_id"],
                    locator=locator,
                ),
            )
        )
    return values


def snippet(row, query):
    value = row.get("text_content")
    if not value:
        return None
    start = value.casefold().find(query.casefold().strip())
    start = max(0, start - 100) if start >= 0 else 0
    return (
        ("…" if start else "")
        + value[start : start + 600]
        + ("…" if start + 600 < len(value) else "")
    )
