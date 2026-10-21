"""Frozen experiment identity and explicit uncertainty in sequence labels."""

import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from evaluation.quality.metrics import score as retrieval_metrics

RECIPES = {
    "uniform12": {"window_ms": 12000, "overlap_ms": 2000, "fps": 1},
    "short4": {"window_ms": 4000, "overlap_ms": 2000, "fps": 1},
    "fine2": {"window_ms": 2000, "overlap_ms": 1000, "fps": 1},
}
FLOORS = (0.65, 0.675, 0.70)
QUERIES = [
    {"id": "fall-1", "family": "fall", "text": "person falling"},
    {"id": "fall-2", "family": "fall", "text": "A person falling to the floor"},
    {"id": "fall-3", "family": "fall", "text": "Someone loses balance and falls down"},
    {"id": "street-1", "family": "street", "text": "person walking on streets"},
    {"id": "sit-1", "family": "sit", "text": "A person sitting down in a chair"},
    {"id": "bend-1", "family": "bend", "text": "A person bending down"},
    {"id": "lie-1", "family": "lie", "text": "A person lying still on the floor"},
    {
        "id": "walk-1",
        "family": "walk",
        "text": "A person walking through an indoor lobby",
    },
    {"id": "fight-1", "family": "fight", "text": "two person fighting"},
    {
        "id": "close-1",
        "family": "close",
        "text": "Two people standing close to each other",
    },
]


class EventReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1)
    action: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    provenance: Literal["human", "agent_observation", "publisher"]
    visibility: Literal["clear", "occluded", "uncertain"]

    @model_validator(mode="after")
    def interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("Event interval must be positive and half-open")
        return self


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_frozen(path: Path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Frozen protocol differs; create a new version")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))


def evaluate_falls(rows, assets, floor, k=10, split="development"):
    """Asset scores and errors on publisher sequence classes, never gold temporal labels."""
    judged = {
        a["asset_id"]: a
        for a in assets
        if a["split"] == split and a.get("sequence_class") in ("fall", "adl")
    }
    relevant = {i for i, a in judged.items() if a["sequence_class"] == "fall"}
    by_asset = {}
    for row in rows:
        if row["asset_id"] in judged and row["score"] >= floor:
            old = by_asset.get(row["asset_id"])
            if old is None or row["score"] > old["score"]:
                by_asset[row["asset_id"]] = row
    ranked = sorted(by_asset.values(), key=lambda r: (-r["score"], r["asset_id"]))[:k]
    accepted = {r["asset_id"] for r in ranked}
    negatives = set(judged) - relevant
    tp = len(accepted & relevant)
    fp = len(accepted & negatives)
    ranking = retrieval_metrics(
        {
            "qrels": [{"asset_id": asset, "grade": 3} for asset in relevant],
            "answerability": "positive",
        },
        [{"asset": {"asset_id": row["asset_id"]}, "citations": []} for row in ranked],
        k=k,
    )
    return {
        "ndcg_at_10": ranking["ndcg_at_10"],
        "scope": "Provisional publisher sequence classification; not temporal or gold retrieval",
        "positive_assets": len(relevant),
        "negative_assets": len(negatives),
        "positive_asset_recall_at_10": tp / len(relevant) if relevant else None,
        "negative_asset_acceptance_rate": fp / len(negatives) if negatives else None,
        "accepted_precision": tp / (tp + fp) if tp + fp else None,
        "accepted": ranked,
        "unjudged_excluded": len({r["asset_id"] for r in rows} - set(judged)),
        "temporal_recall": None,
        "gold_eligible": False,
    }
