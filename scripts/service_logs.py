"""Persist content-free Docker events in bounded, service-specific local logs."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "worker", "dispatcher", "indexer", "embedding", "frontend")
EVENTS = {"request", "request_failed", "task_started", "task_finished", "web_request"}


def safe_event(line):
    """Accept known structured fields only; never copy raw exceptions or URLs."""
    start = line.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(line[start:])
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("event"), str)
        or data["event"] not in EVENTS
    ):
        return None
    result = {"event": data["event"]}
    for key in ("request_id", "trace_id"):
        try:
            result[key] = str(UUID(str(data[key])))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    for key in ("status", "duration_ms", "bytes_sent"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if 0 <= value <= 10**12:
                result[key] = value
    if isinstance(data.get("method"), str) and data["method"] in {
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    }:
        result["method"] = data["method"]
    if isinstance(data.get("state"), str) and data["state"] in {
        "SUCCESS",
        "FAILURE",
        "RETRY",
        "REVOKED",
    }:
        result["state"] = data["state"]
    return result


def loggers():
    result = {}
    for service in SERVICES:
        directory = ROOT / "logs" / ("frontend" if service == "frontend" else "backend")
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        logger = logging.getLogger(f"service-file.{service}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = RotatingFileHandler(
                directory / f"{service}.log",
                maxBytes=5 * 1024**2,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        result[service] = logger
    return result


def command(*args):
    return [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "infra/compose/compose.yaml"),
        *args,
    ]


def run():
    os.umask(0o077)
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    with (local / "service-logs.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        writers = loggers()
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        stopping = False
        child = None

        def stop(*_):
            nonlocal stopping
            stopping = True
            if child is not None and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        since = datetime.now(timezone.utc).isoformat()
        while not stopping:
            # Docker timestamps let a reconnect resume without replaying its history.
            child = subprocess.Popen(
                command(
                    "logs",
                    "--follow",
                    "--no-color",
                    "--timestamps",
                    "--since",
                    since,
                    *SERVICES,
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
            )
            try:
                for line in child.stdout:
                    prefix, separator, payload = line.partition("|")
                    if not separator:
                        continue
                    service = prefix.strip().rsplit("-", 1)[0]
                    if service not in writers:
                        continue
                    timestamp, _, message = payload.strip().partition(" ")
                    event = safe_event(message)
                    if event is not None:
                        event["timestamp"] = timestamp
                        writers[service].info(json.dumps(event, allow_nan=False))
                    try:
                        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    since = timestamp
            finally:
                child.stdout.close()
                if child.poll() is None:
                    child.terminate()
                child.wait()
            if not stopping:
                time.sleep(2)


def start():
    subprocess.run(command("ps", "--quiet"), check=True, stdout=subprocess.DEVNULL)
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "run"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=ROOT,
    )
    for _ in range(60):
        code = process.poll()
        if code is not None:
            if code:
                raise RuntimeError(
                    "Log collector failed to start; run scripts/service_logs.py run for diagnostics"
                )
            break  # Another collector already holds the lock.
        try:
            if (ROOT / ".local/service-logs.lock").read_text() == str(process.pid):
                break
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    else:
        process.terminate()
        process.wait()
        raise RuntimeError("Log collector did not become ready")
    print(
        "Service logs: logs/backend/ and logs/frontend/ (5 MiB × 4 files per service)"
    )


def stop():
    try:
        pid = int((ROOT / ".local/service-logs.lock").read_text())
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if str(Path(__file__).resolve()).encode() in arguments and b"run" in arguments:
            os.kill(pid, signal.SIGTERM)
            for _ in range(60):
                with (ROOT / ".local/service-logs.lock").open("a+") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        return
                    except BlockingIOError:
                        pass
                time.sleep(0.05)
            raise RuntimeError("Log collector is still stopping")
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("start", "run", "stop"), default="start", nargs="?"
    )
    args = parser.parse_args()
    {"start": start, "run": run, "stop": stop}[args.action]()
