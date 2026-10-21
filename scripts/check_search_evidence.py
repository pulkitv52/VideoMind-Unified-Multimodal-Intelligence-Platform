"""Read-only authenticated CPU search/evidence smoke. Not a release relevance benchmark."""

import hashlib
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
POSITIVES = [
    (
        "document",
        "How do I safely open the electrical panel?",
        {"procedure.txt", "scanned-page.pdf", "speech.wav", "spoken.mp4"},
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
    report = {
        "scope": "Retained public/synthetic corpus; local development smoke, not independent relevance evaluation",
        "queries": [],
        "filter_checks": [],
        "originals_verified": 0,
        "citations_verified": 0,
        "viewer_descriptors_verified": 0,
    }
    with httpx.Client(base_url="http://localhost:8080", timeout=180) as c:
        c.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        w = c.get("/api/workspaces").json()[0]["id"]
        base = f"/api/workspaces/{w}"
        titles = {}
        sources = c.get(base + "/sources").json()
        for source in sources:
            after = ""
            while True:
                r = c.get(
                    base + f'/sources/{source["id"]}/assets',
                    params={"limit": 200, **({"after": after} if after else {})},
                )
                r.raise_for_status()
                for asset in r.json():
                    titles[asset["id"]] = asset["title"]
                    original = c.get(
                        base
                        + f'/sources/{source["id"]}/revisions/{asset["revision_id"]}/original'
                    )
                    original.raise_for_status()
                    assert (
                        hashlib.sha256(original.content).hexdigest() == asset["sha256"]
                    )
                    report["originals_verified"] += 1
                after = r.headers.get("x-next-cursor", "")
                if not after:
                    break

        def run(query, filters=None, **options):
            start = time.perf_counter()
            r = c.post(
                base + "/search",
                json={
                    "workspace_id": w,
                    "query": query,
                    "filters": filters or {},
                    **options,
                },
            )
            r.raise_for_status()
            data = r.json()
            assert data["request_id"] == r.headers["x-request-id"]
            report["generation_id"] = data["generation_id"]
            report["profile"] = data["profile"]
            report["retrieval_configuration"] = data["configuration"]
            for hit in data["results"]:
                assert hit["title"] == titles[hit["asset"]["asset_id"]]
                evidence = list(hit["citations"]) + [
                    cite
                    for neighbor in hit["context"]
                    for cite in neighbor["citations"]
                ]
                for cite in evidence:
                    ref = cite["anchor"]["asset"]
                    path = base + f'/sources/{ref["source_id"]}'
                    rr = c.get(path + f'/citations/{cite["id"]}')
                    rr.raise_for_status()
                    resolved = rr.json()
                    assert resolved["revision_id"] == ref["revision_id"]
                    report["citations_verified"] += 1
                cite = hit["citations"][0]
                ref = hit["asset"]
                kind = (
                    "media"
                    if cite["anchor"]["locator"]["kind"] == "temporal"
                    else "document"
                )
                resolved = c.get(
                    base + f'/sources/{ref["source_id"]}/citations/{cite["id"]}'
                ).json()
                descriptor = c.get(
                    base
                    + f'/sources/{ref["source_id"]}/revisions/{ref["revision_id"]}/{kind}',
                    params={"segment_set_id": resolved["segment_set_id"]},
                )
                descriptor.raise_for_status()
                report["viewer_descriptors_verified"] += 1
            return data, round((time.perf_counter() - start) * 1000, 2)

        for label, query, expected in POSITIVES:
            for strategy in ("unified", "per_modality"):
                data, elapsed = run(query, strategy=strategy)
                found = [h["title"] for h in data["results"]]
                assert set(found) & expected, (label, found)
                report["queries"].append(
                    {
                        "label": label,
                        "query": query,
                        "strategy": strategy,
                        "expected_hit_at_10": True,
                        "titles": found,
                        "timings_ms": data["timings_ms"],
                        "including_evidence_checks_ms": elapsed,
                    }
                )
        negative = json.loads(
            (ROOT / "evaluation/reports/phase6-calibration.json").read_text()
        )
        report["negative_queries"] = []
        for item in negative:
            if item["kind"] != "negative":
                continue
            data, _ = run(item["query"])
            assert data["no_useful_evidence"], (
                item["query"],
                [h["title"] for h in data["results"]],
            )
            report["negative_queries"].append(
                {"query": item["query"], "abstained": True}
            )
        for source in sources:
            data, _ = run("People walking or driving", {"source_ids": [source["id"]]})
            assert all(h["asset"]["source_id"] == source["id"] for h in data["results"])
            assert all(f["source_id"] == source["id"] for f in data["facets"])
            report["filter_checks"].append(
                {
                    "source": source["name"],
                    "results": len(data["results"]),
                    "scope_preserved": True,
                }
            )
        for label, query, expected, filters in [
            (
                "silent_native",
                POSITIVES[1][1],
                {"silent.mp4"},
                {"modalities": ["video"], "representations": ["video"]},
            ),
            (
                "non_speech_native",
                POSITIVES[2][1],
                {"beeps.wav"},
                {"modalities": ["audio"], "representations": ["audio"]},
            ),
            (
                "spoken_phrase",
                POSITIVES[0][1],
                {"speech.wav", "spoken.mp4"},
                {"representations": ["transcript"]},
            ),
            (
                "ocr",
                POSITIVES[0][1],
                {"scanned-page.pdf"},
                {"representations": ["ocr"]},
            ),
        ]:
            data, _ = run(query, filters)
            found = {h["title"] for h in data["results"]}
            assert found & expected, (label, found)
            report["filter_checks"].append(
                {"label": label, "expected_hit_at_10": True, "titles": sorted(found)}
            )
        report["readiness"] = c.get("/health/ready").json()
        assert report["readiness"]["retrieval_ready"]
    (ROOT / "evaluation/reports/phase6-corpus.json").write_text(
        json.dumps(report, indent=2)
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "originals_verified",
                    "citations_verified",
                    "viewer_descriptors_verified",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
