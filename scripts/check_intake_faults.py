"""Fault checks for disposable intake fixtures in this local Compose project."""

import json
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

from demo_intake import ROOT, call, ensure_source, wait

COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "infra/compose/compose.yaml"),
]


def command(*args):
    return subprocess.run(
        [*COMPOSE, *args], check=True, capture_output=True, text=True
    ).stdout


def main():
    call("/api/auth/login", json.loads((ROOT / ".local/owner.json").read_text()))
    w = call("/api/workspaces")[0]["id"]
    tag = "verification-" + uuid4().hex[:10]
    folder = ROOT / ".local/imports" / tag
    folder.mkdir(mode=0o755)
    file = folder / "notes.txt"
    file.write_text("version one")
    file.chmod(0o644)
    report = {}
    sources = []
    try:
        connected = ensure_source(w, "Disposable folder " + tag, "local_folder", tag)
        sources.append(connected["id"])
        base = f"/api/workspaces/{w}/sources/{connected['id']}"
        assert all(j["status"] == "stored" for j in wait(base))
        first = call(base + "/assets")
        assert len(first) == 1
        file.write_text("version two")
        call(base + "/sync", {})
        assert all(j["status"] == "stored" for j in wait(base))
        second = call(base + "/assets")
        assert second[0]["revision_id"] != first[0]["revision_id"]
        report["folder_changed_bytes_new_revision"] = True
        file.unlink()
        call(base + "/sync", {})
        wait(base)
        assert call(base + "/assets") == []
        report["folder_removed_file_tombstoned"] = True
        (folder / "escape.txt").symlink_to(ROOT / "README.md")
        call(base + "/sync", {})
        failed = wait(base)[0]
        assert failed["status"] == "failed"
        report["symlink_rejected"] = True
        source = ensure_source(w, "Disposable faults " + tag, "upload")
        sources.append(source["id"])
        upload_base = f"/api/workspaces/{w}/sources/{source['id']}"
        print(
            "Stopping worker to verify durable queued upload and broker-independent recovery",
            flush=True,
        )
        command("stop", "worker")
        accepted = call(
            upload_base + "/files?filename_value=queued.txt",
            b"durable before worker restart",
            raw=True,
        )
        assert any(
            j["id"] == accepted["job_id"] and j["status"] == "queued"
            for j in call(upload_base + "/jobs")
        )
        # Drop only this demo's broker delivery by stopping Redis while keeping its volume intact.
        command("stop", "redis")
        command("start", "redis")
        command("start", "worker")
        assert all(j["status"] == "stored" for j in wait(upload_base))
        report["worker_restart_queued_upload_recovered"] = True
        report["redis_restart_no_job_loss"] = True
        # Exercise lease recovery/fencing with a deterministic expired attempt under the runtime role.
        runtime = """from sqlalchemy import text
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
from videomind.ingestion.service import finish
import json,sys
v=json.loads(sys.stdin.read())
e=database(Settings().database_url.get_secret_value())
with transaction(e,v['actor']) as c:
 c.execute(text("UPDATE app.ingestion_jobs SET status='queued',available_at=now() WHERE workspace_id=:w AND source_id=:s AND id=:j"),v)
with e.begin() as c:
 old=c.execute(text('SELECT app.intake_claim(:w,:s,:j)'),v).scalar_one()
 assert old
with transaction(e,v['actor']) as c:
 c.execute(text("UPDATE app.ingestion_jobs SET lease_expires_at=now()-interval '1 second' WHERE workspace_id=:w AND source_id=:s AND id=:j"),v)
with e.begin() as c:
 new=c.execute(text('SELECT app.intake_claim(:w,:s,:j)'),v).scalar_one()
 assert new and new['lease_token']!=old['lease_token']
assert not finish(e,old,'stored',{'stale':True})
assert finish(e,new,'stored',{'original_stored':True,'format_validated':True,'searchable':False})
print('fenced')
"""
        command("stop", "worker")
        actor = call("/api/auth/me")["id"]
        payload = json.dumps(
            {"w": w, "s": source["id"], "j": accepted["job_id"], "actor": actor}
        )
        # Pass script as an argument and fixture values via stdin, without any credentials.
        output = subprocess.run(
            [*COMPOSE, "exec", "-T", "api", "python", "-c", runtime],
            input=payload,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        assert "fenced" in output
        report["expired_lease_reclaimed_and_stale_finish_rejected"] = True
        command("start", "worker")
        target = ROOT / "evaluation/reports/phase2-faults.json"
        target.write_text(json.dumps(report, indent=2) + "\n")
        print("Intake fault checks passed:", target, flush=True)
    finally:
        command("start", "redis", "worker")
        for source in sources:
            import urllib.request
            from demo_intake import client

            req = urllib.request.Request(
                f"http://127.0.0.1:8080/api/workspaces/{w}/sources/{source}",
                method="DELETE",
            )
            with client.open(req, timeout=15):
                pass
        shutil.rmtree(folder)


if __name__ == "__main__":
    main()
