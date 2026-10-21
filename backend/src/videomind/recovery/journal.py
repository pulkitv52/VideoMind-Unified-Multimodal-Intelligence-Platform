"""Copy committed events to an independent, fsynced volume; never log payloads."""

import argparse
import fcntl
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager

from sqlalchemy import text
from videomind.infrastructure.database import database

MAX_EVENTS = 100000


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS events(position INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL)"
    )
    connection.commit()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def persist(path, lineage, events):
    """Idempotent export; never advance a max-sequence cursor past late commits."""
    with connect(path) as out:
        prior = out.execute("SELECT value FROM meta WHERE key='lineage'").fetchone()
        if prior and prior[0] != lineage:
            raise ValueError("Recovery lineage mismatch")
        out.execute("INSERT OR IGNORE INTO meta VALUES('lineage',?)", (lineage,))
        for event in events:
            payload = json.dumps(event, sort_keys=True, default=str)
            old = out.execute(
                "SELECT payload FROM events WHERE event_id=?", (str(event["event_id"]),)
            ).fetchone()
            if old and old[0] != payload:
                raise ValueError("Recovery event identity conflict")
            out.execute(
                "INSERT OR IGNORE INTO events(event_id,payload) VALUES(?,?)",
                (str(event["event_id"]), payload),
            )
        out.execute(
            "INSERT OR REPLACE INTO meta VALUES('last_success',?)", (str(time.time()),)
        )
    directory = os.open(str(Path(path).parent), os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def sync(engine, path):
    # Transaction locks release on errors and cannot leak into the connection pool.
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL statement_timeout='10s'"))
        conn.execute(text("SELECT pg_advisory_xact_lock(814207319)"))
        lineage = str(
            conn.execute(
                text("SELECT lineage FROM recovery.identity WHERE id=1")
            ).scalar_one()
        )
        events = [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM recovery.events ORDER BY sequence LIMIT :n"),
                {"n": MAX_EVENTS + 1},
            ).mappings()
        ]
        if len(events) > MAX_EVENTS:
            raise ValueError("Recovery journal capacity exceeded")
        persist(path, lineage, events)
        return {"events": len(events), "lineage": lineage}


def export(path):
    with connect(path) as conn:
        lineage = conn.execute("SELECT value FROM meta WHERE key='lineage'").fetchone()
        last = conn.execute(
            "SELECT value FROM meta WHERE key='last_success'"
        ).fetchone()
        if not lineage or not last:
            raise ValueError("Recovery journal not initialized")
        events = [
            json.loads(r[0])
            for r in conn.execute("SELECT payload FROM events ORDER BY position")
        ]
        if len(events) > MAX_EVENTS:
            raise ValueError("Recovery journal capacity exceeded")
        return {"lineage": lineage[0], "last_success": float(last[0]), "events": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("serve", "sync", "export", "health"),
        default="serve",
        nargs="?",
    )
    args = parser.parse_args()
    path = Path(os.environ.get("VM_RECOVERY_JOURNAL", "/recovery/journal.sqlite3"))
    if args.action == "health":
        data = export(path)
        if time.time() - data["last_success"] > 30:
            raise SystemExit(1)
        return
    engine = database(os.environ["VM_RECOVERY_DATABASE_URL"])
    try:
        if args.action in ("sync", "export"):
            result = sync(engine, path)
            print(json.dumps(export(path) if args.action == "export" else result))
            return
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (path.parent / "export.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            while True:
                try:
                    sync(engine, path)
                except Exception:
                    logging.error("Recovery export failed; journal health is stale")
                time.sleep(2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
