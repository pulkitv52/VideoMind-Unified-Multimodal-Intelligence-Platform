"""Coarse observed concurrent memory; distinguish samples from true peaks."""

import json
import re
import subprocess
import time
from evaluation.quality.recovery import command


def mib(value):
    number, unit = re.match(r"([\d.]+)([A-Za-z]+)", value).groups()
    return (
        float(number) * {"B": 1 / 1048576, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unit]
    )


def collect(root, samples=12, interval=5):
    rows = []
    start = time.perf_counter()
    for _ in range(samples):
        raw = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"], text=True
        )
        services = [json.loads(line) for line in raw.splitlines() if line.strip()]
        services = [
            {k: r[k] for k in ("Name", "MemUsage", "CPUPerc", "PIDs")}
            for r in services
            if r["Name"].startswith("videomind-") and "-run-" not in r["Name"]
        ]
        rows.append(
            {
                "elapsed_seconds": time.perf_counter() - start,
                "services": services,
                "total_mib": sum(mib(r["MemUsage"]) for r in services),
            }
        )
        if len(rows) < samples:
            time.sleep(interval)
    peak = subprocess.run(
        command(root, "exec", "-T", "embedding", "cat", "/sys/fs/cgroup/memory.peak"),
        capture_output=True,
        text=True,
    )
    report = {
        "scope": "Observed concurrent samples during bounded evaluation; not instantaneous true peak",
        "sample_interval_seconds": interval,
        "samples": rows,
        "max_observed_total_mib": max(r["total_mib"] for r in rows),
        "embedding_cgroup_memory_peak_bytes_since_container_start": (
            int(peak.stdout.strip())
            if peak.returncode == 0 and peak.stdout.strip().isdigit()
            else None
        ),
        "cgroup_peak_is_run_specific": False,
    }
    (root / "evaluation/reports/phase7-resources.json").write_text(
        json.dumps(report, indent=2)
    )
    return report
