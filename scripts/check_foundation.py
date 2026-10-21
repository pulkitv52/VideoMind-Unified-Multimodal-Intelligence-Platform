"""Exercise this local stack's readiness and persistence; retain a sanitized report."""

import http.cookiejar
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "infra/compose/compose.yaml"),
]


def command(args, **kwargs):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, **kwargs
    ).stdout


def request(client, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = client.open(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        value = response.read()
        return response.status, json.loads(value) if value else None


def wait_ready(client):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            status, value = request(client, "/health/ready")
            if status == 200 and value["ready"]:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Local stack did not become ready")


def runtime(code):
    return command([*COMPOSE, "exec", "-T", "api", "python", "-"], input=code)


def main():
    client = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    report = {"scope": "Phase 1 CPU-only foundation; no inference model loaded"}
    report["initial_readiness"] = wait_ready(client)
    credentials = json.loads((ROOT / ".local/owner.json").read_text())
    assert request(client, "/api/auth/login", credentials)[0] == 200
    status, original = request(client, "/api/workspaces")
    assert status == 200 and original
    key = ".verification/persistence-" + uuid4().hex
    common = """from videomind.config import Settings
from videomind.infrastructure.services import object_client, redis_client
from videomind.infrastructure.database import database
from sqlalchemy import text
import io, json
settings=Settings()
objects=object_client(settings)
redis=redis_client(settings)
"""
    runtime(
        common
        + f'objects.put_object(settings.minio_bucket,{key!r},io.BytesIO(b"persistence"),11)\nredis.set({key!r},"persistence")\n'
    )
    print(
        "Restarting only VideoMind services; checking persisted database session, Redis and object bytes",
        flush=True,
    )
    command(
        [*COMPOSE, "restart", "postgres", "redis", "minio", "api", "worker", "frontend"]
    )
    report["post_restart_readiness"] = wait_ready(client)
    status, current = request(client, "/api/workspaces")
    assert status == 200 and current == original
    result = runtime(
        common + f"""response=objects.get_object(settings.minio_bucket,{key!r})
try: assert response.read()==b"persistence"
finally: response.close(); response.release_conn()
assert redis.get({key!r})=="persistence"
objects.remove_object(settings.minio_bucket,{key!r})
redis.delete({key!r})
for item in objects.list_objects(settings.minio_bucket,prefix=".verification/persistence-"):
 objects.remove_object(settings.minio_bucket,item.object_name)
for leftover in redis.scan_iter(match=".verification/persistence-*"):
 redis.delete(leftover)
engine=database(settings.database_url.get_secret_value())
with engine.connect() as conn:
 print(json.dumps({{"postgres":conn.execute(text("SELECT version()")).scalar_one(),"pgvector":conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar_one(),"migration":conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()}}))
engine.dispose()
"""
    )
    report["versions"] = json.loads(result)
    report["persistence"] = {
        "existing_http_session": True,
        "workspace_rows": True,
        "redis_value": True,
        "object_bytes": True,
    }
    print("Checking readiness with Redis stopped", flush=True)
    try:
        command([*COMPOSE, "stop", "redis"])
        status, value = request(client, "/health/ready")
        assert status == 503 and not value["ready"]
        report["redis_failure_returns_503"] = True
    finally:
        command([*COMPOSE, "start", "redis"])
    report["recovered_readiness"] = wait_ready(client)
    ids = command([*COMPOSE, "ps", "-q"]).split()
    stats = command(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids])
    report["idle_container_stats"] = [json.loads(line) for line in stats.splitlines()]
    report["host_meminfo_kib"] = {
        line.split(":")[0]: int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:"))
    }
    target = ROOT / "evaluation/reports/phase1-2026-10-18.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(
        "Persistence and dependency failure checks passed; sanitized report:",
        target,
        flush=True,
    )


if __name__ == "__main__":
    main()
