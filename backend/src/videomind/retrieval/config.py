"""Versioned local retrieval policy. Threshold is calibrated by the smoke manifest."""

import hashlib
import json

POLICY = {
    "version": "hybrid-v1",
    "dense_candidates": 150,
    "lexical_candidates": 150,
    "identifier_candidates": 50,
    "rrf_k": 60,
    "asset_cap_first_ten": 3,
    "neighbors": 2,
    "minimum_dense_cosine": 0.70,
    "group_overlap": 0.5,
    "dense_backend": "exact_cosine",
    "calibration": "phase6-local-development-v1",
}


def configuration(body):
    value = dict(POLICY, mode=body.mode, strategy=body.strategy)
    if getattr(body, "query_kind", "text") == "image":
        value.update(
            query_kind="image",
            query_recipe="still-rgb-exif-640-png-v1",
            calibration="image-query-pilot-uncalibrated",
        )
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value, digest
