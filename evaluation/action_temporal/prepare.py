"""Prepare reviewable labels, grouping, producer identity and source-time provenance."""

import json
import hashlib
from pathlib import Path
import av
from evaluation.quality.labels import checked, intervals
from evaluation.action_temporal.protocol import (
    RECIPES,
    FLOORS,
    QUERIES,
    digest,
    write_frozen,
)

CORE = {
    "caviar-Rest_FallOnFloor",
    "caviar-Rest_InChair",
    "caviar-Walk1",
    "caviar-Fight_Chase",
}
RESERVED = {"urfall-fall-03", "urfall-fall-05", "urfall-adl-03", "urfall-adl-28"}


def prepare(root, corpus):
    items = json.loads((root / "evaluation/manifests/video30.json").read_text())[
        "items"
    ]
    assets = []
    for item in items:
        key = item["id"]
        if not (
            key.startswith("urfall-") or key in CORE or key.startswith("roadscapes-")
        ):
            continue
        path = checked(root, item["derivative"])
        asset = next(a for a in corpus["assets"] if a["title"] == path.name)
        if asset["sha256"] != item["derivative"]["sha256"]:
            raise ValueError("Retained original mismatch")
        mapping = root / item["derivative"]["mapping_path"]
        if (
            hashlib.sha256(mapping.read_bytes()).hexdigest()
            != item["derivative"]["mapping_sha256"]
        ):
            raise ValueError("Mapping changed")
        with av.open(str(path)) as c:
            duration = round(c.duration / 1000)
        publisher = []
        if key in CORE:
            annotation = checked(root, item["annotation"])
            frames = json.loads(mapping.read_text())["mapping"]
            for term in {
                "caviar-Rest_FallOnFloor": ["drop down", "immobile"],
                "caviar-Rest_InChair": ["immobile"],
                "caviar-Walk1": ["walking"],
                "caviar-Fight_Chase": ["fighting"],
            }[key]:
                publisher.extend(intervals(annotation, frames, term))
        assets.append(
            {
                "asset_key": key,
                "asset_id": asset["id"],
                "revision_id": asset["revision_id"],
                "source_id": asset["source_id"],
                "title": asset["title"],
                "sha256": asset["sha256"],
                "path": str(path.relative_to(root)),
                "duration_ms": duration,
                "mapping_path": str(mapping.relative_to(root)),
                "mapping_sha256": item["derivative"]["mapping_sha256"],
                "group": key,
                "actor_session_identity": "unknown; no actor-independent claim",
                "split": "reserved_diagnostic" if key in RESERVED else "development",
                "sequence_class": (
                    "fall"
                    if key.startswith("urfall-fall-")
                    else "adl" if key.startswith("urfall-adl-") else None
                ),
                "sequence_label_provenance": item["label_kind"],
                "publisher_context_intervals": publisher,
            }
        )
    assets.sort(key=lambda a: a["asset_key"])
    protocol = {
        "version": 1,
        "scope": "AT0/AT1 development pilot; not independent release gold",
        "corpus_sha256": corpus["sha256"],
        "profile": corpus["profile"],
        "generation_id": corpus["generation_id"],
        "workspace_id": corpus["workspace_id"],
        "assets": assets,
        "queries": QUERIES,
        "recipes": RECIPES,
        "floors": list(FLOORS),
        "candidate_budget": 150,
        "result_budget": 10,
        "asset_cap": 1,
        "preprocessing": {
            "jpeg_quality": 85,
            "max_edge": 640,
            "sampling": "Rounded original PTS; next sample = selected PTS + 1000ms; no temporal oracle",
        },
        "max_new_windows_per_batch": 32,
        "batch_wall_seconds": 1200,
        "reserved_policy": "Do not score reserved groups or choose policy from them; split is sequence-level diagnostic only, not unseen actor/session data",
        "gold_eligible": False,
        "human_reviewers": [],
    }
    protocol["sha256"] = digest(protocol)
    write_frozen(root / "evaluation/manifests/action-temporal-v1.json", protocol)
    review = root / "evaluation/annotations/action-temporal-v1-review.json"
    if not review.exists():
        write_frozen(
            review,
            {
                "protocol_sha256": protocol["sha256"],
                "adjudicated": False,
                "independent_reviewers": [],
                "boundary_definition": "First transition toward floor through first settled floor posture; lying afterward is separate",
                "assets": [
                    {
                        "asset_key": a["asset_key"],
                        "asset_id": a["asset_id"],
                        "revision_id": a["revision_id"],
                        "duration_ms": a["duration_ms"],
                        "events": [],
                        "absence_labels": [],
                        "status": "needs_human_review",
                        "development_feedback": (
                            "User identified visible fall; exact interval still needs review"
                            if a["asset_key"] == "urfall-fall-04"
                            else ""
                        ),
                    }
                    for a in assets
                ],
            },
        )
    return protocol
