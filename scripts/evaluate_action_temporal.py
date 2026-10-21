"""AT0/AT1 offline action experiments; authenticated replay, no index publication."""

import argparse
import json
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.action_temporal.prepare import prepare
from evaluation.action_temporal.replay import replay
from evaluation.action_temporal.windows import run
from evaluation.action_temporal.assessment import assess
from evaluation.action_temporal.inspection import inspect
from evaluation.action_temporal.calibration import calibrate
from evaluation.action_temporal.protocol import digest
from evaluation.quality.corpus import freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=["prepare", "baseline", "windows", "assess", "inspect", "calibrate"],
    )
    p.add_argument(
        "--recipe", choices=["uniform12", "short4", "fine2"], default="uniform12"
    )
    p.add_argument("--max-new-windows", type=int, default=32)
    args = p.parse_args()
    if args.action in ("inspect", "calibrate"):
        protocol = json.loads(
            (ROOT / "evaluation/manifests/action-temporal-v1.json").read_text()
        )
        if args.action == "calibrate":
            report = calibrate(ROOT, protocol)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "selected_policy": report["selected_diagnostic_policy"],
                        "reserved_quality_scored": report["reserved_quality_scored"],
                    }
                )
            )
            return
        report = inspect(ROOT, protocol)
        print(
            json.dumps(
                {"development_assets": len(report["sheets"]), "gold_eligible": False}
            )
        )
        return
    corpus = json.loads((ROOT / "evaluation/manifests/phase7-corpus.json").read_text())
    with httpx.Client(base_url="http://localhost:8080", timeout=180) as client:
        client.post(
            "/api/auth/login", json=json.loads((ROOT / ".local/owner.json").read_text())
        ).raise_for_status()
        if args.action == "prepare":
            current = freeze(client, ROOT)
            if current["sha256"] != corpus["sha256"]:
                raise ValueError("Frozen source/index changed")
            protocol = prepare(ROOT, corpus)
            print(
                json.dumps(
                    {
                        "assets": len(protocol["assets"]),
                        "queries": len(protocol["queries"]),
                        "protocol_sha256": protocol["sha256"],
                        "human_gold": False,
                    }
                )
            )
            return
        protocol = json.loads(
            (ROOT / "evaluation/manifests/action-temporal-v1.json").read_text()
        )
        unsigned = {k: v for k, v in protocol.items() if k != "sha256"}
        if (
            digest(unsigned) != protocol["sha256"]
            or protocol["corpus_sha256"] != corpus["sha256"]
        ):
            raise ValueError("Protocol identity changed")
        if args.action == "baseline":
            report = replay(ROOT, client, protocol)
            print(json.dumps({"replayed_queries": len(report["rows"])}))
        elif args.action == "assess":
            report = assess(ROOT, protocol)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "complete_recipes": report["complete_recipes"],
                    }
                )
            )
        else:
            report = run(ROOT, protocol, args.recipe, max_new=args.max_new_windows)
            print(
                json.dumps(
                    {
                        k: report[k]
                        for k in (
                            "recipe",
                            "complete",
                            "expected_windows",
                            "encoded_windows",
                            "gold_eligible",
                        )
                    }
                )
            )


if __name__ == "__main__":
    main()
