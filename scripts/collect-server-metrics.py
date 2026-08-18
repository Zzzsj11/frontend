#!/usr/bin/env python3
"""Collect one host-level sample using Linux procfs and Docker CLI; emits JSON."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def cpu_times() -> tuple[int, int]:
    values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def memory() -> tuple[int, int]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    return values.get("MemTotal", 0), values.get("MemAvailable", 0)


def default_interface() -> str:
    for line in Path("/proc/net/route").read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 2:
            return fields[0]
    return os.getenv("SERVER_MONITOR_INTERFACE", "eth0")


def network(interface: str) -> tuple[int, int]:
    base = Path("/sys/class/net") / interface / "statistics"
    return int((base / "tx_bytes").read_text()), int((base / "rx_bytes").read_text())


def percent(raw: str) -> float:
    try:
        return float(raw.strip().rstrip("%"))
    except ValueError:
        return 0.0


def containers() -> list[dict]:
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        rows.append(
            {
                "name": item.get("Name", ""),
                "cpuPercent": percent(item.get("CPUPerc", "0")),
                "memoryPercent": percent(item.get("MemPerc", "0")),
                "memoryUsage": item.get("MemUsage", ""),
                "networkIO": item.get("NetIO", ""),
                "blockIO": item.get("BlockIO", ""),
            }
        )
    return rows


def main() -> None:
    interface = default_interface()
    total1, idle1 = cpu_times()
    tx1, rx1 = network(interface)
    started = time.monotonic()
    time.sleep(1)
    total2, idle2 = cpu_times()
    tx2, rx2 = network(interface)
    elapsed = max(0.001, time.monotonic() - started)
    cpu = (1 - (idle2 - idle1) / max(1, total2 - total1)) * 100
    mem_total, mem_available = memory()
    disk = shutil.disk_usage("/")
    load1, load5, load15 = os.getloadavg()
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    print(
        json.dumps(
            {
                "source": os.getenv("SERVER_MONITOR_SOURCE", "primary"),
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "bootId": boot_id,
                "interface": interface,
                "cpuPercent": round(max(0, min(cpu, 100)), 2),
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "memoryTotalBytes": mem_total,
                "memoryAvailableBytes": mem_available,
                "diskTotalBytes": disk.total,
                "diskAvailableBytes": disk.free,
                "networkTxBytesTotal": tx2,
                "networkRxBytesTotal": rx2,
                "networkTxBps": max(0, tx2 - tx1) / elapsed,
                "networkRxBps": max(0, rx2 - rx1) / elapsed,
                "containers": containers(),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
