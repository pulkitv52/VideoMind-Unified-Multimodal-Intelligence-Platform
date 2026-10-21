"""Separate cold loading, warm request distribution and failed request counts."""

import json
import subprocess
import time
from evaluation.quality.metrics import percentile
from evaluation.quality.recovery import command


def run(root, client, manifest):
    start = time.perf_counter()
    subprocess.run(
        command(root, "restart", "embedding"), check=True, capture_output=True
    )
    available = False
    for _ in range(90):
        try:
            available = bool(client.get("/health/ready").json().get("retrieval_ready"))
        except Exception:
            available = False
        if available:
            break
        time.sleep(1)
    if not available:
        raise ValueError("Embedding service did not restart")
    base = f'/api/workspaces/{manifest["workspace_id"]}/search'

    def measure(query):
        started = time.perf_counter()
        response = client.post(
            base, json={"workspace_id": manifest["workspace_id"], "query": query}
        )
        elapsed = (time.perf_counter() - started) * 1000
        data = response.json()
        if response.status_code == 200 and (
            data["generation_id"] != manifest["generation_id"]
            or data["profile"] != manifest["profile"]
        ):
            raise ValueError("Performance run generation/profile changed")
        return {
            "query": query,
            "status": response.status_code,
            "elapsed_ms": elapsed,
            "timings_ms": data.get("timings_ms"),
        }

    cold = measure("Repeated electronic beeping tones")
    texts = [
        "two person fighting",
        "A person falling to the floor",
        "Repeated electronic beeping tones",
        "How do I safely open the electrical panel?",
        "A red square moving across a white background",
        "A close-up photograph of an orange cat",
    ]
    warm = [measure(q) for _ in range(10) for q in texts]
    successful = [r["elapsed_ms"] for r in warm if r["status"] == 200]
    report = {
        "scope": "Single client, retained 46-asset/197-vector corpus; explicit model process restart for cold run; not ingestion throughput or scale",
        "corpus_sha256": manifest["sha256"],
        "generation_id": manifest["generation_id"],
        "profile": manifest["profile"],
        "os_file_cache_controlled": False,
        "cold": cold,
        "restart_to_cold_response_seconds": time.perf_counter()
        - start
        - sum(r["elapsed_ms"] for r in warm) / 1000,
        "warm": warm,
        "warm_failed_requests": sum(r["status"] != 200 for r in warm),
        "warm_success_latency_ms": {
            f"p{int(q*100)}": percentile(successful, q) for q in (0.5, 0.95, 0.99)
        },
    }
    (root / "evaluation/reports/phase7-performance.json").write_text(
        json.dumps(report, indent=2)
    )
    return report
