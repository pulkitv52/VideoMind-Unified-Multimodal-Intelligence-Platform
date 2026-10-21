"""Private coordinated backups and guarded disposable restores. No primary restore."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from evaluation.quality.recovery import SNAPSHOT, RESTORE, command, read_exact

# Take pg_dump from the SAME exported PostgreSQL snapshot as the object inventory.
SNAPSHOT = SNAPSHOT.replace(
    "try:\n  inventory=",
    "c.commit()\n c.execution_options(isolation_level='REPEATABLE READ')\n try:\n  snapshot_id=c.execute(text('SELECT pg_export_snapshot()')).scalar_one()\n  inventory=",
).replace(
    "{'inventory':inventory,'counts':counts}",
    "{'snapshot_id':snapshot_id,'inventory':inventory,'counts':counts}",
)

CHECK = r"""
import json,sys,os,re
from sqlalchemy import text
from sqlalchemy.engine import make_url
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
x=json.loads(sys.stdin.read());db=x['database']
if not re.fullmatch(r'videomind_restore_[0-9a-f]{12}',db):raise ValueError('Disposable database required')
s=Settings();base=make_url(s.database_url.get_secret_value());engine=database(base.set(username='videomind_owner',password=os.environ['VM_BACKUP_DB_PASSWORD'],database=db));runtime=database(base.set(database=db))
with engine.begin() as c:
 lineage=str(c.execute(text('SELECT lineage FROM recovery.identity WHERE id=1')).scalar_one())
 journal=x.get('journal');replayed=0
 if journal:
  if journal['lineage']!=lineage:raise ValueError('Journal lineage mismatch')
  # Replay only events not present in the saved snapshot. This preserves re-additions.
  for event in journal['events']:
   if c.execute(text('SELECT 1 FROM recovery.events WHERE event_id=:id UNION ALL SELECT 1 FROM recovery.replayed_events WHERE event_id=:id'),{'id':event['event_id']}).first():continue
   args={'w':event['workspace_id'],'s':event['source_id'],'a':event['asset_id'],'deleted':event['deleted']}
   if event['kind']=='workspace':
    c.execute(text('DELETE FROM app.workspaces WHERE id=:w'),args)
   elif event['kind']=='source':
    c.execute(text("UPDATE app.sources SET deleted=:deleted,status=CASE WHEN :deleted THEN 'disconnected' ELSE 'connected' END WHERE workspace_id=:w AND id=:s"),args)
   elif event['kind']=='asset':
    c.execute(text('UPDATE app.assets SET deleted=:deleted WHERE workspace_id=:w AND source_id=:s AND id=:a'),args)
   else:raise ValueError('Invalid recovery entity')
   # Record replay receipts separately; primary export identities cannot be reused.
   c.execute(text('INSERT INTO recovery.replayed_events(event_id) VALUES(:id) ON CONFLICT DO NOTHING'),{'id':event['event_id']})
   replayed+=1
 counts={name:c.execute(text('SELECT count(*) FROM app.'+name)).scalar_one() for name in ('objects','assets','asset_revisions','segments','embeddings','citation_records','generation_assets')}
 dangling=c.execute(text('SELECT count(*) FROM app.citation_records cr LEFT JOIN app.evidence_anchors ea ON (ea.workspace_id,ea.source_id,ea.id)=(cr.workspace_id,cr.source_id,cr.anchor_id) WHERE ea.id IS NULL')).scalar_one()
 probe=None
 if x.get('probe'):
  p=x['probe'];probe=c.execute(text('SELECT a.deleted AS asset_deleted,s.deleted AS source_deleted FROM app.assets a JOIN app.sources s ON (s.workspace_id,s.id)=(a.workspace_id,a.source_id) WHERE a.workspace_id=:w AND a.source_id=:s AND a.id=:a'),p).mappings().first()
  if not probe:raise ValueError('Probe missing from restored snapshot')
  probe=dict(probe)
 exposed=c.execute(text('SELECT count(*) FROM app.generation_assets ga JOIN app.assets a ON (a.workspace_id,a.source_id,a.id)=(ga.workspace_id,ga.source_id,ga.asset_id) JOIN app.sources s ON (s.workspace_id,s.id)=(a.workspace_id,a.source_id) WHERE a.deleted OR s.deleted')).scalar_one()
 if dangling or exposed:raise ValueError('Restored evidence/publication integrity failed')
with transaction(runtime,'00000000-0000-0000-0000-000000000001') as c:
 if c.execute(text('SELECT count(*) FROM app.embeddings')).scalar_one():raise ValueError('Runtime isolation failed')
if x.get('probe'):
 with engine.connect() as c:
  actor=c.execute(text("SELECT principal_id FROM app.memberships WHERE workspace_id=:w AND role='owner' LIMIT 1"),x['probe']).scalar_one()
 with transaction(runtime,actor) as c:probe['source_access']=c.execute(text('SELECT app.source_access(:w,:s)'),x['probe']).scalar_one()
print(json.dumps({'probe':probe,'counts':counts,'journal_events_replayed':replayed,'dangling_citations':dangling,'deleted_assets_published':exposed,'runtime_isolation':True}))
engine.dispose();runtime.dispose()
"""


def environment(root):
    env = dict(os.environ)
    secrets = dict(
        line.split("=", 1)
        for line in (root / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    env["VM_BACKUP_DB_PASSWORD"] = secrets["POSTGRES_PASSWORD"]
    env["VM_BACKUP_STORAGE_PASSWORD"] = secrets["MINIO_ROOT_PASSWORD"]
    return env


def remote(root, source, payload=None, objects=None, log=None):
    prefix = command(
        root,
        "exec",
        "-T",
        "-e",
        "VM_BACKUP_DB_PASSWORD",
        "-e",
        "VM_BACKUP_STORAGE_PASSWORD",
        "api",
        "python",
        "-c",
        source,
    )
    child = subprocess.Popen(
        prefix,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        env=environment(root),
    )
    try:
        child.stdin.write(json.dumps(payload).encode() + b"\n")
        child.stdin.flush()
        if objects:
            for item in payload["inventory"]:
                with (objects / item["sha256"]).open("rb") as inp:
                    while chunk := inp.read(65536):
                        child.stdin.write(chunk)
        child.stdin.close()
        data = child.stdout.read()
        child.wait(timeout=30)
        if child.returncode:
            raise ValueError("Recovery subprocess failed; inspect private log")
        return json.loads(data)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def journal_export(root, fresh=True):
    invocation = (
        ["-m", "videomind.recovery.journal", "export"]
        if fresh
        else [
            "-c",
            "import json; from videomind.recovery.journal import export; print(json.dumps(export('/recovery/journal.sqlite3')))",
        ]
    )
    data = subprocess.run(
        command(root, "exec", "-T", "recovery-journal", "python", *invocation),
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(data.stdout)


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as inp:
        while chunk := inp.read(65536):
            value.update(chunk)
    return value.hexdigest()


def verify(target):
    manifest = json.loads((target / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("Incomplete backup")
    if sha(target / "database.dump") != manifest["dump_sha256"]:
        raise ValueError("Database checksum mismatch")
    if (
        len(manifest["inventory"]) > 2000
        or sum(i["size_bytes"] for i in manifest["inventory"]) > 536870912
    ):
        raise ValueError("Backup inventory exceeds operator bounds")
    for item in manifest["inventory"]:
        if (
            not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
            or not isinstance(item["size_bytes"], int)
            or item["size_bytes"] < 0
        ):
            raise ValueError("Invalid backup object identity")
        path = target / "objects" / item["sha256"]
        if path.stat().st_size != item["size_bytes"] or sha(path) != item["sha256"]:
            raise ValueError("Object checksum mismatch")
    if sha(target / "journal.json") != manifest["journal_sha256"]:
        raise ValueError("Journal checksum mismatch")
    return manifest


def create(root):
    parent = root / ".local/backups"
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (parent / "operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Bound automatic disk use; never silently remove an older recovery point.
        if (
            sum(p.stat().st_size for p in parent.rglob("*") if p.is_file())
            > 4 * 1024**3
        ):
            raise ValueError("Backup storage budget exceeded; review retention")
        backup_id = uuid4().hex[:12]
        target = parent / (backup_id + ".incomplete")
        target.mkdir(mode=0o700)
        process = None
        with (target / "private.log").open("wb") as log:
            os.chmod(log.name, 0o600)
            try:
                journal_export(root)
                process = subprocess.Popen(
                    command(
                        root,
                        "exec",
                        "-T",
                        "-e",
                        "VM_BACKUP_DB_PASSWORD",
                        "api",
                        "python",
                        "-c",
                        SNAPSHOT,
                    ),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    env=environment(root),
                )
                snapshot = json.loads(process.stdout.readline())
                dump = target / "database.dump"
                with dump.open("wb") as out:
                    subprocess.run(
                        command(
                            root,
                            "exec",
                            "-T",
                            "postgres",
                            "pg_dump",
                            "-U",
                            "videomind_owner",
                            "-d",
                            "videomind",
                            "-Fc",
                            "--no-owner",
                            "--snapshot",
                            snapshot["snapshot_id"],
                        ),
                        stdout=out,
                        stderr=log,
                        check=True,
                        timeout=180,
                    )
                dump.chmod(0o600)
                projected = sum(
                    p.stat().st_size for p in parent.rglob("*") if p.is_file()
                ) + sum(i["size_bytes"] for i in snapshot["inventory"])
                if projected > 4 * 1024**3:
                    raise ValueError(
                        "Backup storage budget exceeded; snapshot remains incomplete"
                    )
                process.stdin.write(b"go\n")
                process.stdin.flush()
                (target / "objects").mkdir(mode=0o700)
                for item in snapshot["inventory"]:
                    header = json.loads(process.stdout.readline())
                    if header["size"] != item["size_bytes"]:
                        raise ValueError("Snapshot framing mismatch")
                    content = read_exact(process.stdout, item["size_bytes"])
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise ValueError("Source checksum mismatch")
                    path = target / "objects" / item["sha256"]
                    path.write_bytes(content)
                    path.chmod(0o600)
                if not json.loads(process.stdout.readline())["complete"]:
                    raise ValueError("Incomplete stream")
                process.stdin.close()
                process.wait(timeout=10)
                if process.returncode:
                    raise ValueError("Snapshot producer failed")
                journal = journal_export(root)
                jp = target / "journal.json"
                jp.write_text(json.dumps(journal))
                jp.chmod(0o600)
                manifest = {
                    "version": 1,
                    "status": "complete",
                    "created_at": time.time(),
                    "inventory": snapshot["inventory"],
                    "counts": snapshot["counts"],
                    "lineage": journal["lineage"],
                    "dump_sha256": sha(dump),
                    "journal_sha256": sha(jp),
                    "scope": "Local same-disk backup; no off-device protection",
                }
                path = target / "manifest.json"
                path.write_text(json.dumps(manifest, indent=2))
                path.chmod(0o600)
                verify(target)
                # Commit backup completion after every payload and directory is fsynced.
                files = [p for p in target.rglob("*") if p.is_file()]
                directories = sorted(
                    [p for p in target.rglob("*") if p.is_dir()],
                    key=lambda p: len(p.parts),
                    reverse=True,
                )
                for path in [*files, *directories, target]:
                    fd = os.open(path, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                complete = parent / backup_id
                target.rename(complete)
                fd = os.open(parent, os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return complete
            finally:
                if process and process.poll() is None:
                    process.kill()
                    process.wait()


def drill(root, target, probe=None):
    manifest = verify(target)
    run = uuid4().hex[:12]
    clone = "videomind_restore_" + run
    bucket = "vm-restore-" + run
    request = {"database": clone, "bucket": bucket, "inventory": manifest["inventory"]}
    if probe:
        request["probe"] = probe
    made_db = False
    made_bucket = False
    with (target / "restore.log").open("wb") as log:
        os.chmod(log.name, 0o600)
        try:
            subprocess.run(
                command(
                    root,
                    "exec",
                    "-T",
                    "postgres",
                    "createdb",
                    "-U",
                    "videomind_owner",
                    clone,
                ),
                stdout=log,
                stderr=log,
                check=True,
                timeout=30,
            )
            made_db = True
            with (target / "database.dump").open("rb") as inp:
                subprocess.run(
                    command(
                        root,
                        "exec",
                        "-T",
                        "postgres",
                        "pg_restore",
                        "-U",
                        "videomind_owner",
                        "-d",
                        clone,
                        "--no-owner",
                    ),
                    stdin=inp,
                    stdout=log,
                    stderr=log,
                    check=True,
                    timeout=180,
                )
            made_bucket = True
            object_check = remote(
                root, RESTORE, request | {"action": "objects"}, target / "objects", log
            )
            before = remote(root, CHECK, request, log=log)
            if before["counts"] != manifest["counts"]:
                raise ValueError("Snapshot count mismatch")
            saved_journal = json.loads((target / "journal.json").read_text())
            saved_check = remote(
                root, CHECK, request | {"journal": saved_journal}, log=log
            )
            journal = journal_export(root)
            if journal["lineage"] != manifest["lineage"]:
                raise ValueError("Backup/journal lineage mismatch")
            after = remote(root, CHECK, request | {"journal": journal}, log=log)
            repeated = remote(root, CHECK, request | {"journal": journal}, log=log)
            if repeated["journal_events_replayed"]:
                raise ValueError("Journal replay is not idempotent")
            report = {
                "snapshot_verified": before,
                "saved_journal_replay": saved_check,
                "repeated_replay_events": repeated["journal_events_replayed"],
                "after_journal_replay": after,
                **object_check,
                "primary_restored": False,
                "backup_id": target.name,
                "journal_age_seconds": time.time() - journal["last_success"],
            }
            path = root / "evaluation/reports/local-recovery-drill.json"
            path.write_text(json.dumps(report, indent=2))
            return report
        finally:
            try:
                if made_bucket:
                    remote(root, RESTORE, request | {"action": "cleanup"}, log=log)
            finally:
                if made_db:
                    subprocess.run(
                        command(
                            root,
                            "exec",
                            "-T",
                            "postgres",
                            "dropdb",
                            "-U",
                            "videomind_owner",
                            "--force",
                            clone,
                        ),
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=30,
                    )
