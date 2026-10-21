"""Measured HTTP runs with raw provenance and reproducible evaluation modes."""

import json
import time
from evaluation.quality.metrics import score, summarize, percentile


def run(client, manifest, qrels, output):
    all_rows = []
    w = manifest["workspace_id"]
    for strategy in ("unified", "per_modality"):
        for mode in ("hybrid", "native_dense", "lexical", "derived_dense"):
            rows = []
            for query in qrels["queries"]:
                started = time.perf_counter()
                filters = dict(query["filters"])
                if mode == "native_dense":
                    filters["representations"] = [
                        r
                        for r in filters.get(
                            "representations", ["image", "video", "audio"]
                        )
                        if r in ("image", "video", "audio")
                    ]
                response = client.post(
                    f"/api/workspaces/{w}/search",
                    json={
                        "workspace_id": w,
                        "query": query["query"],
                        "filters": filters,
                        "mode": "dense" if mode == "native_dense" else mode,
                        "strategy": strategy,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if (
                    data["generation_id"] != manifest["generation_id"]
                    or data["profile"] != manifest["profile"]
                ):
                    raise ValueError("Frozen generation/profile changed")
                for hit in data["results"]:
                    asset = next(
                        a
                        for a in manifest["assets"]
                        if a["id"] == hit["asset"]["asset_id"]
                    )
                    if asset["revision_id"] != hit["asset"]["revision_id"]:
                        raise ValueError("Frozen original changed")
                row = {
                    "query_id": query["id"],
                    "family": query["family"],
                    "slice": query["slice"],
                    "split": query["split"],
                    "mode": mode,
                    "strategy": strategy,
                    "metrics": score(query, data["results"]),
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    "response": data,
                }
                rows.append(row)
                all_rows.append(row)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Crash-safe progress: raw runs are retained after each complete configuration.
            report = {
                "scope": qrels["scope"],
                "corpus_sha256": manifest["sha256"],
                "rows": all_rows,
                "configuration_summaries": {},
            }
            for key in {(r["mode"], r["strategy"]) for r in all_rows}:
                selected = [r for r in all_rows if (r["mode"], r["strategy"]) == key]
                times = [r["elapsed_ms"] for r in selected]
                report["configuration_summaries"]["/".join(key)] = {
                    "overall": summarize(selected),
                    "slices": {
                        s: summarize([r for r in selected if r["slice"] == s])
                        for s in {r["slice"] for r in selected}
                    },
                    "http_latency_ms": {
                        f"p{int(q*100)}": percentile(times, q)
                        for q in (0.5, 0.95, 0.99)
                    },
                    "requests": len(selected),
                }
            temp = output.with_suffix(".tmp")
            temp.write_text(json.dumps(report, indent=2))
            temp.replace(output)
            print(f"{mode}/{strategy}: {len(rows)} measured requests", flush=True)
    return report
