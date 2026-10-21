"""Local backup operator. No command restores the primary database."""

import argparse
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operations.recovery import create, drill, verify, journal_export


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("create", "verify", "drill", "status", "export-journal")
    )
    parser.add_argument("--backup-id")
    args = parser.parse_args()

    def deadline(*_):
        raise TimeoutError("Backup operator exceeded ten-minute deadline")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(600)
    if args.action == "export-journal":
        data = journal_export(ROOT, fresh=False)
        target = ROOT / ".local" / f"recovery-journal-{time.time_ns()}.json"
        with target.open("x") as out:
            json.dump(data, out)
            out.flush()
            os.fsync(out.fileno())
        print(
            json.dumps(
                {
                    "path": str(target),
                    "events": len(data["events"]),
                    "last_export_age_seconds": time.time() - data["last_success"],
                    "primary_database_contacted": False,
                }
            )
        )
        return
    if args.action == "create":
        target = create(ROOT)
        print(
            json.dumps(
                {
                    "backup_id": target.name,
                    "status": "verified",
                    "scope": "local same disk",
                }
            )
        )
        return
    parent = ROOT / ".local/backups"
    available = sorted(
        (
            p
            for p in parent.glob("*")
            if re.fullmatch(r"[a-f0-9]{12}", p.name) and (p / "manifest.json").is_file()
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if args.action == "status":
        try:
            journal = journal_export(ROOT)
            health = {
                "available": True,
                "last_export_age_seconds": time.time() - journal["last_success"],
                "events": len(journal["events"]),
            }
        except Exception:
            health = {"available": False}
        latest = (
            json.loads((available[-1] / "manifest.json").read_text())
            if available
            else None
        )
        print(
            json.dumps(
                {
                    "complete_backup_ids": [p.name for p in available],
                    "latest_backup_age_hours": (
                        (time.time() - latest["created_at"]) / 3600 if latest else None
                    ),
                    "journal": health,
                    "automatic_retention": "none; four-GiB admission budget; manual review required",
                }
            )
        )
        return
    if args.backup_id:
        if not re.fullmatch(r"[a-f0-9]{12}", args.backup_id):
            raise ValueError("Invalid backup ID")
        target = parent / args.backup_id
    elif available:
        target = available[-1]
    else:
        raise ValueError("No completed operational backup")
    result = (
        drill(ROOT, target)
        if args.action == "drill"
        else {
            "backup_id": target.name,
            "status": "verified",
            "objects": len(verify(target)["inventory"]),
        }
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
