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


def cpu_times() -> tuple[int, int, int]:
    values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle, values[4] if len(values) > 4 else 0


def memory() -> tuple[int, int, int, int]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    return values.get("MemTotal", 0), values.get("MemAvailable", 0), values.get("SwapTotal", 0), values.get("SwapFree", 0)


def block_devices() -> dict[str, tuple[int, int, int, int]]:
    rows = {}
    for line in Path("/proc/diskstats").read_text().splitlines():
        fields = line.split()
        if len(fields) < 14 or fields[2].startswith(("loop", "ram", "dm-")):
            continue
        rows[fields[2]] = (int(fields[3]), int(fields[5]) * 512, int(fields[7]), int(fields[9]) * 512)
    return rows


def filesystem_rows() -> list[dict]:
    rows = []
    seen = set()
    for path in ("/", "/var/lib/docker", os.getenv("SERVER_MONITOR_DATA_PATH", "/opt")):
        try:
            resolved = str(Path(path).resolve())
            stats, inodes = shutil.disk_usage(path), os.statvfs(path)
        except OSError:
            continue
        key = (stats.total, resolved)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"path": path, "totalBytes": stats.total, "availableBytes": stats.free, "inodeTotal": inodes.f_files, "inodeFree": inodes.f_ffree})
    return rows


def size_bytes(raw: str) -> int:
    raw = raw.strip().replace("iB", "B").upper()
    units = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
    for unit in ("TB", "GB", "MB", "KB", "B"):
        if raw.endswith(unit):
            try:
                return int(float(raw[:-len(unit)]) * units[unit])
            except ValueError:
                return 0
    return 0


def io_pair(raw: str) -> tuple[int, int]:
    parts = raw.split(" / ")
    return (size_bytes(parts[0]), size_bytes(parts[1])) if len(parts) == 2 else (0, 0)


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
                "memoryUsedBytes": size_bytes(str(item.get("MemUsage", "")).split(" / ")[0]),
                "networkRxBytes": io_pair(item.get("NetIO", ""))[0],
                "networkTxBytes": io_pair(item.get("NetIO", ""))[1],
                "blockReadBytes": io_pair(item.get("BlockIO", ""))[0],
                "blockWriteBytes": io_pair(item.get("BlockIO", ""))[1],
                "pids": int(item.get("PIDs") or 0),
            }
        )
    return rows


def main() -> None:
    interface = default_interface()
    total1, idle1, iowait1 = cpu_times()
    tx1, rx1 = network(interface)
    disks1 = block_devices()
    started = time.monotonic()
    time.sleep(1)
    total2, idle2, iowait2 = cpu_times()
    tx2, rx2 = network(interface)
    disks2 = block_devices()
    elapsed = max(0.001, time.monotonic() - started)
    cpu = (1 - (idle2 - idle1) / max(1, total2 - total1)) * 100
    mem_total, mem_available, swap_total, swap_free = memory()
    disk = shutil.disk_usage("/")
    load1, load5, load15 = os.getloadavg()
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    disk_delta = [0, 0, 0, 0]
    for name, after in disks2.items():
        before = disks1.get(name, after)
        for index in range(4):
            disk_delta[index] += max(0, after[index] - before[index])
    print(
        json.dumps(
            {
                "source": os.getenv("SERVER_MONITOR_SOURCE", "primary"),
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "bootId": boot_id,
                "interface": interface,
                "cpuPercent": round(max(0, min(cpu, 100)), 2),
                "cpuIowaitPercent": round(max(0, (iowait2 - iowait1) / max(1, total2 - total1) * 100), 2),
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "memoryTotalBytes": mem_total,
                "memoryAvailableBytes": mem_available,
                "swapTotalBytes": swap_total,
                "swapFreeBytes": swap_free,
                "diskTotalBytes": disk.total,
                "diskAvailableBytes": disk.free,
                "networkTxBytesTotal": tx2,
                "networkRxBytesTotal": rx2,
                "networkTxBps": max(0, tx2 - tx1) / elapsed,
                "networkRxBps": max(0, rx2 - rx1) / elapsed,
                "diskReadIops": disk_delta[0] / elapsed,
                "diskReadBps": disk_delta[1] / elapsed,
                "diskWriteIops": disk_delta[2] / elapsed,
                "diskWriteBps": disk_delta[3] / elapsed,
                "filesystems": filesystem_rows(),
                "containers": containers(),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
