"""Coordinated local backup and isolated restore drill. Never restores primary.

Backups include authentication records and must remain under private .local.
The replay probe uses a synthetic post-backup tombstone in the clone. It does
not establish a durable primary deletion journal or scheduled backup RPO.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

SNAPSHOT = """
import json,sys,os
from sqlalchemy import text
from sqlalchemy.engine import make_url
from videomind.config import Settings
from videomind.infrastructure.database import database
from videomind.infrastructure.services import object_client
s=Settings();url=make_url(s.database_url.get_secret_value()).set(username='videomind_owner',password=os.environ['VM_BACKUP_DB_PASSWORD']);engine=database(url);objects=object_client(s)
with engine.connect() as c:
 c.execute(text('SELECT pg_advisory_lock(814207312)'))
 try:
  inventory=[dict(r) for r in c.execute(text('SELECT workspace_id,source_id,id,bucket,object_key,sha256,size_bytes,mime_type FROM app.objects ORDER BY workspace_id,source_id,id')).mappings()]
  if sum(r['size_bytes'] for r in inventory)>536870912 or len(inventory)>2000:raise ValueError('Backup admission limit')
  counts={name:c.execute(text('SELECT count(*) FROM app.'+name)).scalar_one() for name in ('objects','assets','asset_revisions','segments','embeddings','citation_records','generation_assets')}
  print(json.dumps({'inventory':inventory,'counts':counts},default=str),flush=True)
  if sys.stdin.buffer.readline().strip()!=b'go':raise ValueError('Snapshot aborted')
  for item in inventory:
   print(json.dumps({'size':item['size_bytes']}),flush=True)
   obj=objects.get_object(item['bucket'],item['object_key'])
   try:
    for chunk in obj.stream(65536):sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
   finally:obj.close();obj.release_conn()
  print(json.dumps({'complete':True}),flush=True)
 finally:c.execute(text('SELECT pg_advisory_unlock(814207312)'))
engine.dispose()
"""

RESTORE = """
import hashlib,io,json,os,re,sys
from sqlalchemy import text
from sqlalchemy.engine import make_url
from minio import Minio
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
x=json.loads(sys.stdin.buffer.readline());db=x['database'];bucket=x['bucket']
if not re.fullmatch(r'videomind_restore_[0-9a-f]{12}',db) or not re.fullmatch(r'vm-restore-[0-9a-f]{12}',bucket):raise ValueError('Isolated target required')
s=Settings();base=make_url(s.database_url.get_secret_value());engine=database(base.set(username='videomind_owner',password=os.environ['VM_BACKUP_DB_PASSWORD'],database=db));runtime=database(base.set(database=db));objects=Minio(s.minio_endpoint,access_key='videomind-root',secret_key=os.environ['VM_BACKUP_STORAGE_PASSWORD'],secure=False)
if x['action']=='objects':
 objects.make_bucket(bucket)
 for item in x['inventory']:
  content=sys.stdin.buffer.read(item['size_bytes'])
  if len(content)!=item['size_bytes'] or hashlib.sha256(content).hexdigest()!=item['sha256']:raise ValueError('Backup integrity')
  objects.put_object(bucket,item['object_key'],io.BytesIO(content),len(content),content_type=item['mime_type'])
 for item in x['inventory']:
  obj=objects.get_object(bucket,item['object_key'])
  try:
   digest=hashlib.sha256()
   for chunk in obj.stream(65536):digest.update(chunk)
   if digest.hexdigest()!=item['sha256']:raise ValueError('Restored object integrity')
  finally:obj.close();obj.release_conn()
 print(json.dumps({'objects_restored_and_verified':len(x['inventory'])}),flush=True)
elif x['action']=='validate':
 with engine.begin() as c:
  actor=c.execute(text('SELECT principal_id FROM app.memberships WHERE workspace_id=:w AND role=:role LIMIT 1'),{'w':x['workspace'],'role':'owner'}).scalar_one()
  # Verify complete snapshot relationships before an isolated post-backup delete.
  counts={name:c.execute(text('SELECT count(*) FROM app.'+name)).scalar_one() for name in ('objects','assets','asset_revisions','segments','embeddings','citation_records','generation_assets')}
  dangling=c.execute(text('SELECT count(*) FROM app.citation_records cr LEFT JOIN app.segments sg ON (sg.workspace_id,sg.source_id,sg.id)=(cr.workspace_id,cr.source_id,cr.segment_id) LEFT JOIN app.evidence_anchors ea ON (ea.workspace_id,ea.source_id,ea.id)=(cr.workspace_id,cr.source_id,cr.anchor_id) WHERE sg.id IS NULL OR ea.id IS NULL')).scalar_one()
  if dangling:raise ValueError('Restored citation integrity')
  if x.get('tombstone'):
   c.execute(text('UPDATE app.assets SET deleted=true WHERE workspace_id=:w AND source_id=:s AND id=:a'),x['tombstone'])
 with transaction(runtime,actor) as c:
  active=c.execute(text('SELECT count(*) FROM app.generation_assets ga JOIN app.workspace_search_state st ON (st.workspace_id,st.active_generation_id)=(ga.workspace_id,ga.generation_id) WHERE ga.workspace_id=:w'),{'w':x['workspace']}).scalar_one()
  published=c.execute(text('SELECT count(*) FROM app.generation_assets WHERE workspace_id=:w AND asset_id=:a'),{'w':x['workspace'],'a':x['asset']}).scalar_one()
 with transaction(runtime,'00000000-0000-0000-0000-000000000001') as c:
  if c.execute(text('SELECT count(*) FROM app.embeddings')).scalar_one():raise ValueError('Restored runtime isolation')
 if x.get('tombstone') and published:raise ValueError('Tombstone replay failed')
 from pydantic import SecretStr
 from fastapi.testclient import TestClient
 from videomind.main import create_app
 checks=0
 if not x.get('tombstone'):
  settings=s.model_copy(update={'database_url':SecretStr(base.set(database=db).render_as_string(hide_password=False)),'minio_bucket':bucket,'minio_access_key':'videomind-root','minio_secret_key':SecretStr(os.environ['VM_BACKUP_STORAGE_PASSWORD'])})
  with engine.connect() as c:
   citations=[dict(r) for r in c.execute(text('SELECT id,source_id FROM app.citation_records WHERE workspace_id=:w'),{'w':x['workspace']}).mappings()]
  with TestClient(create_app(settings)) as tc:
   tc.cookies.set('videomind_session',x['session'])
   for cr in citations:
    response=tc.get('/api/workspaces/'+x['workspace']+'/sources/'+str(cr['source_id'])+'/citations/'+str(cr['id']))
    if response.status_code!=200:raise ValueError('Restored citation unavailable')
    checks+=1
 print(json.dumps({'counts':counts,'active_assets':active,'probe_asset_memberships':published,'dangling_citations':dangling,'runtime_isolation':True,'http_citations':checks}),flush=True)
elif x['action']=='cleanup':
 for item in objects.list_objects(bucket,recursive=True):objects.remove_object(bucket,item.object_name)
 objects.remove_bucket(bucket);print(json.dumps({'cleaned':True}),flush=True)
engine.dispose();runtime.dispose()
"""


def command(root, *args):
    return [
        "docker",
        "compose",
        "--env-file",
        str(root / ".env"),
        "-f",
        str(root / "infra/compose/compose.yaml"),
        *args,
    ]


def read_exact(stream, size):
    remaining = size
    chunks = []
    while remaining:
        value = stream.read(min(65536, remaining))
        if not value:
            raise ValueError("Truncated backup stream")
        chunks.append(value)
        remaining -= len(value)
    return b"".join(chunks)


def drill(root, manifest, session):
    started = time.perf_counter()
    run = uuid4().hex[:12]
    target = root / ".local/backups" / run
    target.mkdir(mode=0o700, parents=True)
    env = dict(os.environ)
    secrets = dict(
        line.split("=", 1)
        for line in (root / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    env["VM_BACKUP_DB_PASSWORD"] = secrets["POSTGRES_PASSWORD"]
    env["VM_BACKUP_STORAGE_PASSWORD"] = secrets["MINIO_ROOT_PASSWORD"]
    exec_prefix = command(
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
    )
    log = (target / "private.log").open("wb")
    process = None
    clone = "videomind_restore_" + run
    bucket = "vm-restore-" + run
    created = False
    objects_created = False
    report = {
        "scope": "Isolated restore drill; primary never restored; tombstone replay uses clone-only fixture journal",
        "scheduled_backups": False,
        "durable_primary_tombstone_journal": False,
        "backup_private": True,
    }
    try:
        process = subprocess.Popen(
            exec_prefix + [SNAPSHOT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            env=env,
            cwd=root,
        )
        snapshot = json.loads(process.stdout.readline())
        inventory = snapshot["inventory"]
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
                ),
                stdout=out,
                stderr=log,
                check=True,
            )
        dump.chmod(0o600)
        process.stdin.write(b"go\n")
        process.stdin.flush()
        (target / "objects").mkdir(mode=0o700)
        for item in inventory:
            header = json.loads(process.stdout.readline())
            if header["size"] != item["size_bytes"]:
                raise ValueError("Snapshot size mismatch")
            content = read_exact(process.stdout, item["size_bytes"])
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Snapshot checksum mismatch")
            path = target / "objects" / item["sha256"]
            path.write_bytes(content)
            path.chmod(0o600)
        if not json.loads(process.stdout.readline())["complete"]:
            raise ValueError("Incomplete snapshot")
        process.stdin.close()
        process.wait(timeout=10)
        if process.returncode:
            raise ValueError("Snapshot producer failed")
        (target / "inventory.json").write_text(json.dumps(inventory, indent=2))
        (target / "inventory.json").chmod(0o600)
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
            check=True,
            stdout=log,
            stderr=log,
        )
        created = True

        def restore_db(clean=False):
            with dump.open("rb") as source:
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
                        *(["--clean", "--if-exists"] if clean else []),
                    ),
                    stdin=source,
                    stdout=log,
                    stderr=log,
                    check=True,
                )

        restore_db()
        request = {
            "database": clone,
            "bucket": bucket,
            "inventory": inventory,
            "workspace": manifest["workspace_id"],
            "asset": manifest["assets"][0]["id"],
            "session": session,
        }

        def remote(payload, send_objects=False):
            child = subprocess.Popen(
                exec_prefix + [RESTORE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                env=env,
                cwd=root,
            )
            try:
                child.stdin.write(json.dumps(payload).encode() + b"\n")
                child.stdin.flush()
                if send_objects:
                    for item in inventory:
                        with (target / "objects" / item["sha256"]).open("rb") as inp:
                            while chunk := inp.read(65536):
                                child.stdin.write(chunk)
                    child.stdin.flush()
                child.stdin.close()
                value = child.stdout.readline()
                child.wait(timeout=120)
                if child.returncode or not value:
                    raise ValueError(
                        "Isolated restore check failed; inspect private backup log"
                    )
                return json.loads(value)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()

        objects_created = True
        report.update(remote(request | {"action": "objects"}, True))
        report["initial_restore"] = remote(request | {"action": "validate"})
        if report["initial_restore"]["counts"] != snapshot["counts"]:
            raise ValueError("Restored counts differ from coordinated snapshot")
        if report["initial_restore"]["active_assets"] != len(manifest["assets"]):
            raise ValueError("Restored active generation coverage")
        asset = manifest["assets"][0]
        event = {
            "w": manifest["workspace_id"],
            "s": asset["source_id"],
            "a": asset["id"],
        }
        report["deleted_clone"] = remote(
            request | {"action": "validate", "tombstone": event}
        )
        restore_db(True)
        report["fixture_tombstone_replay"] = remote(
            request | {"action": "validate", "tombstone": event}
        )
        report["dump_sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
        report["bytes"] = sum(i["size_bytes"] for i in inventory)
        report["seconds"] = time.perf_counter() - started
        remote(request | {"action": "cleanup"})
        objects_created = False
        (root / "evaluation/reports/phase7-recovery.json").write_text(
            json.dumps(report, indent=2)
        )
        return report
    finally:
        if process and process.poll() is None:
            process.stdin.close()
            process.terminate()
            process.wait(timeout=10)
        if created:
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
            )
        if objects_created:
            try:
                remote(request | {"action": "cleanup"})
            except Exception:
                log.write(
                    ("Unfinished disposable restore bucket: " + bucket + "\n").encode()
                )
        log.close()
