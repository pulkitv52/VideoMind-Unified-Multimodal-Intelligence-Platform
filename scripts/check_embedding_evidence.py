"""Authenticated local embedding acceptance checks; --activate permits cutover.

Uses local owner credentials without printing them. Does not alter source content.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    (
        "safety",
        "How do I safely open the electrical panel?",
        {"procedure.txt", "speech.wav", "spoken.mp4", "scanned-page.png"},
    ),
    (
        "visual",
        "A red square moving across a white background",
        {"silent.mp4", "spoken.mp4"},
    ),
    ("sound", "Repeated electronic beeping tones", {"beeps.wav"}),
    ("image", "A close-up photograph of an orange cat", {"chelsea.png"}),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    report = {
        "scope": "Small retained corpus, CPU vector/evidence checks; not a broad relevance benchmark",
        "originals_verified": 0,
        "citations_verified": 0,
        "queries": [],
        "filtered_checks": [],
    }
    with httpx.Client(base_url="http://localhost:8080", timeout=180) as client:
        client.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        w = client.get("/api/workspaces").json()[0]["id"]
        base = f"/api/workspaces/{w}/indexes"
        status = client.get(base)
        status.raise_for_status()
        data = status.json()
        building = next(
            (g for g in data["generations"] if g["status"] == "building"), None
        )
        if args.activate and building:
            coverage = building["coverage"]
            assert coverage["eligible_assets"] == coverage[
                "published_assets"
            ] and not coverage.get("pending_extraction_assets")
            client.post(base + f'/{building["id"]}/activate').raise_for_status()
            data = client.get(base).json()
        active = next(g for g in data["generations"] if g["status"] == "active")
        report["generation_id"] = active["id"]
        report["profile"] = active["fingerprint"]
        report["coverage"] = active["coverage"]
        sources = client.get(f"/api/workspaces/{w}/sources").json()
        originals = {}
        titles = {}
        for source in sources:
            assets = []
            after = ""
            while True:
                r = client.get(
                    f'/api/workspaces/{w}/sources/{source["id"]}/assets',
                    params={"limit": 200, **({"after": after} if after else {})},
                )
                r.raise_for_status()
                assets.extend(r.json())
                after = r.headers.get("x-next-cursor", "")
                if not after:
                    break
            for a in assets:
                path = f'/api/workspaces/{w}/sources/{source["id"]}/revisions/{a["revision_id"]}/original'
                r = client.get(path)
                r.raise_for_status()
                assert hashlib.sha256(r.content).hexdigest() == a["sha256"]
                report["originals_verified"] += 1
                assert a["embedding_status"] == "indexed", (
                    a["title"],
                    a["embedding_status"],
                )
                originals[a["revision_id"]] = a["sha256"]
                titles[a["revision_id"]] = a["title"]
        for label, query, relevant in QUERIES:
            runs = []
            for ann in (False, True):
                start = time.perf_counter()
                r = client.post(
                    base + "/probe", json={"query": query, "ann": ann, "limit": 10}
                )
                r.raise_for_status()
                elapsed = time.perf_counter() - start
                result = r.json()
                assert (
                    result["generation_id"] == active["id"]
                    and result["profile"] == active["fingerprint"]
                )
                names = []
                for item in result["items"]:
                    citation = client.get(
                        f'/api/workspaces/{w}/sources/{item["source_id"]}/citations/{item["citation_id"]}'
                    )
                    citation.raise_for_status()
                    c = citation.json()
                    assert (
                        c["segment_id"] == item["segment_id"]
                        and c["revision_id"] in originals
                    )
                    report["citations_verified"] += 1
                    names.append(titles[c["revision_id"]])
                runs.append(
                    {
                        "ann": ann,
                        "seconds": elapsed,
                        "ids": [i["embedding_id"] for i in result["items"]],
                        "titles": names,
                        "scores": [i["score"] for i in result["items"]],
                    }
                )
            exact, approx = runs
            recall = len(set(exact["ids"]) & set(approx["ids"])) / len(
                set(exact["ids"])
            )
            report["queries"].append(
                {
                    "label": label,
                    "query": query,
                    "runs": runs,
                    "ann_overlap_at_10": recall,
                    "expected_file_in_exact_top10": bool(
                        set(exact["titles"]) & relevant
                    ),
                }
            )
            assert recall >= 0.95, (label, recall)
        # All source filters must remain inside that source; small scopes can
        # legitimately use the exact fallback when fewer than k vectors exist.
        for source in sources:
            r = client.post(
                base + "/probe",
                json={
                    "query": "People and activities",
                    "ann": True,
                    "limit": 10,
                    "source_id": source["id"],
                },
            )
            r.raise_for_status()
            items = r.json()["items"]
            assert all(i["source_id"] == source["id"] for i in items)
            report["filtered_checks"].append(
                {"source": source["name"], "results": len(items)}
            )
        r = client.get("/health/ready")
        r.raise_for_status()
        report["readiness"] = r.json()
    (ROOT / "evaluation/reports/phase5-corpus.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "originals_verified",
                    "citations_verified",
                    "coverage",
                    "filtered_checks",
                    "readiness",
                )
            },
            indent=2,
        )
    )
    print(
        "Query smoke results:",
        [
            (q["label"], q["expected_file_in_exact_top10"], q["ann_overlap_at_10"])
            for q in report["queries"]
        ],
    )


if __name__ == "__main__":
    main()
