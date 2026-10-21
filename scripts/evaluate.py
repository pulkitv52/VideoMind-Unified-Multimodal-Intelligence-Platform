"""Local evaluation commands. Source corpus and credentials stay on this machine."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.quality import (
    corpus,
    search,
    ablation,
    recovery,
    resources,
    performance,
    diagnose,
    comparison,
    release,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "freeze",
            "search",
            "ablate",
            "recovery",
            "resources",
            "performance",
            "diagnose",
            "assess",
        ],
    )
    args = parser.parse_args()
    with httpx.Client(base_url="http://localhost:8080", timeout=180) as client:
        client.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        if args.action == "freeze":
            manifest = corpus.freeze(client, ROOT)
            existing = ROOT / "evaluation/manifests/phase7-corpus.json"
            labels = ROOT / "evaluation/annotations/phase7-qrels.json"
            if existing.exists():
                frozen = json.loads(existing.read_text())
                if frozen["sha256"] != manifest["sha256"]:
                    raise ValueError(
                        "Frozen corpus changed; create a new version instead of overwriting labels"
                    )
                print(
                    json.dumps(
                        {
                            "assets": len(manifest["assets"]),
                            "frozen_snapshot_verified": True,
                            "labels_preserved": True,
                        }
                    )
                )
                return
            if labels.exists():
                raise ValueError(
                    "Existing annotation file has no corpus snapshot; preserve it before creating a new version"
                )
            (ROOT / "evaluation/manifests/phase7-corpus.json").write_text(
                json.dumps(manifest, indent=2)
            )
            (ROOT / "evaluation/annotations/phase7-qrels.json").write_text(
                json.dumps(corpus.queries(manifest), indent=2)
            )
            print(
                json.dumps(
                    {
                        "assets": len(manifest["assets"]),
                        "corpus_sha256": manifest["sha256"],
                    }
                )
            )
        else:
            manifest = json.loads(
                (ROOT / "evaluation/manifests/phase7-corpus.json").read_text()
            )
            qrels = json.loads(
                (ROOT / "evaluation/annotations/phase7-qrels.json").read_text()
            )
            if qrels["corpus_sha256"] != manifest["sha256"]:
                raise ValueError("Qrels corpus mismatch")
            if args.action == "search":
                search.run(
                    client,
                    manifest,
                    qrels,
                    ROOT / "evaluation/reports/phase7-search.json",
                )
            elif args.action == "ablate":
                ablation.run(ROOT, manifest, qrels)
            elif args.action == "diagnose":
                diagnose.run(ROOT, client, manifest)
            elif args.action == "performance":
                performance.run(ROOT, client, manifest)
            elif args.action == "resources":
                resources.collect(ROOT)
            elif args.action == "assess":
                reports = ROOT / "evaluation/reports"

                def read(name):
                    return json.loads((reports / f"phase7-{name}.json").read_text())

                current = read("search")
                compared = comparison.compare(read("search-before"), current)
                (reports / "phase7-comparison.json").write_text(
                    json.dumps(compared, indent=2)
                )
                report = release.assess(
                    manifest,
                    qrels,
                    current,
                    read("recovery"),
                    read("verification"),
                    read("performance"),
                    compared,
                )
                paths = [
                    *sorted((ROOT / "evaluation/quality").glob("*.py")),
                    ROOT / "scripts/evaluate.py",
                    ROOT / "backend/src/videomind/retrieval/repository.py",
                    ROOT / "backend/src/videomind/retrieval/routes.py",
                    ROOT / "backend/tests/integration/test_search.py",
                    ROOT / "backend/tests/integration/test_foundation.py",
                ]
                report.update(
                    phase=7,
                    measured_at=datetime.now(timezone.utc).isoformat(),
                    corpus_sha256=manifest["sha256"],
                    generation_id=manifest["generation_id"],
                    profile=manifest["profile"],
                    adopted_sampling_change=False,
                    input_sha256={
                        str(p.relative_to(ROOT)): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in (
                            ROOT / "evaluation/manifests/phase7-corpus.json",
                            ROOT / "evaluation/manifests/phase7-rights.json",
                            ROOT / "evaluation/annotations/phase7-qrels.json",
                        )
                    },
                    source_sha256={
                        str(p.relative_to(ROOT)): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in paths
                    },
                    report_sha256={
                        str(p.relative_to(ROOT)): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in sorted(reports.glob("phase7-*.json"))
                        if p.name != "phase7-assessment.json"
                    },
                )
                (reports / "phase7-assessment.json").write_text(
                    json.dumps(report, indent=2)
                )
                print(
                    json.dumps(
                        {
                            "status": report["status"],
                            "open_gates": len(report["failed_gates"]),
                        }
                    )
                )
            else:
                recovery.drill(ROOT, manifest, client.cookies.get("videomind_session"))


if __name__ == "__main__":
    main()
