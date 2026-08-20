from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    GenerationJobModel,
    LlmCallLogModel,
    ServerAlertEventModel,
    ServerMetricSampleModel,
    ServerTrafficMonthModel,
    utcnow,
)

GIB = 1024**3
WORKER_LIMITS = {"image/video": 4, "export": 1, "chat": 2, "ass/general outline": 2, "storyboard line (API)": 4}


def _percent(used: int | float, total: int | float) -> float:
    return round(float(used) / float(total) * 100, 2) if total else 0.0


def _month_start(value: datetime) -> date:
    local = value.astimezone(ZoneInfo(settings.server_monitor_timezone))
    return local.date().replace(day=1)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))], 2)


async def _workload_snapshot(db: AsyncSession, captured_at: datetime) -> dict[str, Any]:
    """Small DB-derived operational snapshot; no request bodies or private prompts are copied."""
    active_rows = (
        await db.execute(
            select(GenerationJobModel.kind, GenerationJobModel.status, func.count(), func.min(GenerationJobModel.created_at))
            .where(GenerationJobModel.deleted_at.is_(None), GenerationJobModel.status.in_(("queued", "running")))
            .group_by(GenerationJobModel.kind, GenerationJobModel.status)
        )
    ).all()
    queues: dict[str, dict[str, Any]] = {}
    for kind, status, count, oldest in active_rows:
        item = queues.setdefault(kind, {"kind": kind, "queued": 0, "running": 0, "oldestQueuedSeconds": 0})
        item[status] = int(count)
        if status == "queued" and oldest:
            item["oldestQueuedSeconds"] = max(0, int((_aware(captured_at) - _aware(oldest)).total_seconds()))
    since = captured_at - timedelta(hours=1)
    completed = list(
        (
            await db.execute(
                select(GenerationJobModel).where(
                    GenerationJobModel.deleted_at.is_(None),
                    GenerationJobModel.finished_at >= since,
                    GenerationJobModel.status.in_(("succeeded", "failed")),
                )
            )
        ).scalars()
    )
    by_kind: dict[str, dict[str, Any]] = {}
    for job in completed:
        item = by_kind.setdefault(job.kind, {"success": 0, "failed": 0, "queue": [], "execution": [], "end_to_end": [], "observed": 0})
        item["success" if job.status == "succeeded" else "failed"] += 1
        if job.started_at:
            item["queue"].append(max(0, (_aware(job.started_at) - _aware(job.created_at)).total_seconds()))
        if job.started_at and job.finished_at:
            item["execution"].append(max(0, (_aware(job.finished_at) - _aware(job.started_at)).total_seconds()))
        if job.first_result_observed_at:
            item["observed"] += 1
            item["end_to_end"].append(max(0, (_aware(job.first_result_observed_at) - _aware(job.created_at)).total_seconds()))
    for kind, stats in by_kind.items():
        queue = stats.pop("queue")
        execution = stats.pop("execution")
        end_to_end = stats.pop("end_to_end")
        stats.update(
            {
                "kind": kind,
                "queue_wait_seconds": {"avg": round(sum(queue) / len(queue), 2) if queue else 0, "p95": _percentile(queue, 0.95)},
                "execution_seconds": {"avg": round(sum(execution) / len(execution), 2) if execution else 0, "p95": _percentile(execution, 0.95)},
                "end_to_end_seconds": {"avg": round(sum(end_to_end) / len(end_to_end), 2) if end_to_end else 0, "p95": _percentile(end_to_end, 0.95)},
                "observationCoveragePercent": round(stats.pop("observed") / max(1, stats["success"] + stats["failed"]) * 100, 2),
            }
        )
    llm_rows = list((await db.execute(select(LlmCallLogModel).where(LlmCallLogModel.deleted_at.is_(None), LlmCallLogModel.created_at >= since))).scalars())
    durations = [float(row.duration_ms) for row in llm_rows]
    return {
        "queues": sorted(queues.values(), key=lambda x: x["kind"]),
        "completedLastHour": sorted(by_kind.values(), key=lambda x: x["kind"]),
        "llmLastHour": {
            "calls": len(llm_rows),
            "failed": sum(row.status != "ok" for row in llm_rows),
            "tokens": sum(row.total_tokens for row in llm_rows),
            "avgMs": round(sum(durations) / len(durations), 2) if durations else 0,
            "p95Ms": _percentile(durations, 0.95),
        },
        "configuredExecutionLimits": WORKER_LIMITS,
    }


async def ingest_server_metric(db: AsyncSession, payload: dict[str, Any]) -> ServerMetricSampleModel:
    captured_at = datetime.fromisoformat(str(payload["capturedAt"]).replace("Z", "+00:00"))
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    source = str(payload.get("source") or "primary")[:120]
    sample = ServerMetricSampleModel(
        id=f"metric-{uuid.uuid4().hex}",
        source=source,
        captured_at=captured_at,
        boot_id=str(payload.get("bootId") or "")[:80],
        interface=str(payload.get("interface") or "")[:80],
        cpu_percent=float(payload.get("cpuPercent") or 0),
        cpu_iowait_percent=float(payload.get("cpuIowaitPercent") or 0),
        load_1=float(payload.get("load1") or 0),
        load_5=float(payload.get("load5") or 0),
        load_15=float(payload.get("load15") or 0),
        memory_total_bytes=int(payload.get("memoryTotalBytes") or 0),
        memory_available_bytes=int(payload.get("memoryAvailableBytes") or 0),
        swap_total_bytes=int(payload.get("swapTotalBytes") or 0),
        swap_free_bytes=int(payload.get("swapFreeBytes") or 0),
        disk_total_bytes=int(payload.get("diskTotalBytes") or 0),
        disk_available_bytes=int(payload.get("diskAvailableBytes") or 0),
        network_tx_bytes_total=int(payload.get("networkTxBytesTotal") or 0),
        network_rx_bytes_total=int(payload.get("networkRxBytesTotal") or 0),
        network_tx_bps=float(payload.get("networkTxBps") or 0),
        network_rx_bps=float(payload.get("networkRxBps") or 0),
        disk_read_bps=float(payload.get("diskReadBps") or 0),
        disk_write_bps=float(payload.get("diskWriteBps") or 0),
        disk_read_iops=float(payload.get("diskReadIops") or 0),
        disk_write_iops=float(payload.get("diskWriteIops") or 0),
        filesystems=list(payload.get("filesystems") or []),
        containers=list(payload.get("containers") or []),
        workloads=await _workload_snapshot(db, captured_at),
    )
    previous = (
        await db.execute(
            select(ServerMetricSampleModel)
            .where(ServerMetricSampleModel.source == source, ServerMetricSampleModel.deleted_at.is_(None))
            .order_by(ServerMetricSampleModel.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    delta = 0
    if previous and previous.boot_id == sample.boot_id and sample.network_tx_bytes_total >= previous.network_tx_bytes_total:
        delta = sample.network_tx_bytes_total - previous.network_tx_bytes_total
    month = _month_start(captured_at)
    traffic = (
        await db.execute(
            select(ServerTrafficMonthModel).where(
                ServerTrafficMonthModel.source == source,
                ServerTrafficMonthModel.month == month,
                ServerTrafficMonthModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not traffic:
        traffic = ServerTrafficMonthModel(
            id=f"traffic-{uuid.uuid4().hex}",
            source=source,
            month=month,
            quota_bytes=settings.server_traffic_quota_gib * GIB,
            egress_bytes=0,
            last_counter_bytes=sample.network_tx_bytes_total,
            last_boot_id=sample.boot_id,
        )
        db.add(traffic)
    traffic.egress_bytes += max(0, delta)
    traffic.quota_bytes = settings.server_traffic_quota_gib * GIB
    traffic.last_counter_bytes = sample.network_tx_bytes_total
    traffic.last_boot_id = sample.boot_id
    db.add(sample)
    await _evaluate_alerts(db, sample, traffic)
    retention_cutoff = captured_at - timedelta(days=settings.server_metric_retention_days)
    await db.execute(
        update(ServerMetricSampleModel)
        .where(
            ServerMetricSampleModel.captured_at < retention_cutoff,
            ServerMetricSampleModel.deleted_at.is_(None),
        )
        .values(deleted_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return sample


async def _evaluate_alerts(db: AsyncSession, sample: ServerMetricSampleModel, traffic: ServerTrafficMonthModel) -> None:
    memory_used = _percent(sample.memory_total_bytes - sample.memory_available_bytes, sample.memory_total_bytes)
    disk_used = _percent(sample.disk_total_bytes - sample.disk_available_bytes, sample.disk_total_bytes)
    traffic_used = _percent(traffic.egress_bytes, traffic.quota_bytes)
    swap_used = _percent(sample.swap_total_bytes - sample.swap_free_bytes, sample.swap_total_bytes)
    checks = (
        ("cpu", "CPU 使用率过高", sample.cpu_percent, 80.0, 95.0, "%"),
        ("memory", "可用内存不足", memory_used, 80.0, 90.0, "% 已使用"),
        ("disk", "磁盘空间不足", disk_used, 75.0, 90.0, "% 已使用"),
        ("traffic", "月度公网出站流量接近配额", traffic_used, 70.0, 95.0, "% 已使用"),
        ("swap", "Swap 使用率过高", swap_used, 50.0, 80.0, "% 已使用"),
        ("iowait", "磁盘 I/O 等待过高", sample.cpu_iowait_percent, 15.0, 30.0, "%"),
    )
    now = sample.captured_at
    for key, title, value, warning, critical, unit in checks:
        active = (
            await db.execute(
                select(ServerAlertEventModel)
                .where(
                    ServerAlertEventModel.source == sample.source,
                    ServerAlertEventModel.alert_key == key,
                    ServerAlertEventModel.status == "active",
                    ServerAlertEventModel.deleted_at.is_(None),
                )
                .order_by(ServerAlertEventModel.first_triggered_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if value >= warning:
            severity = "critical" if value >= critical else "warning"
            if not active:
                active = ServerAlertEventModel(
                    id=f"alert-{uuid.uuid4().hex}",
                    source=sample.source,
                    alert_key=key,
                    severity=severity,
                    status="active",
                    title=title,
                    message="",
                    current_value=value,
                    threshold_value=critical if severity == "critical" else warning,
                    first_triggered_at=now,
                    last_observed_at=now,
                    details={},
                )
                db.add(active)
            active.severity = severity
            active.current_value = value
            active.threshold_value = critical if severity == "critical" else warning
            active.last_observed_at = now
            active.message = f"当前 {value:.2f}{unit}，阈值 {active.threshold_value:.0f}{unit}"
        elif active and value < warning - 5:
            active.status = "resolved"
            active.resolved_at = now
            active.last_observed_at = now
            active.current_value = value


def metric_json(item: ServerMetricSampleModel) -> dict[str, Any]:
    memory_used = _percent(item.memory_total_bytes - item.memory_available_bytes, item.memory_total_bytes)
    disk_used = _percent(item.disk_total_bytes - item.disk_available_bytes, item.disk_total_bytes)
    return {
        "capturedAt": item.captured_at.isoformat(),
        "cpuPercent": item.cpu_percent,
        "cpuIowaitPercent": item.cpu_iowait_percent,
        "load": [item.load_1, item.load_5, item.load_15],
        "memoryUsedPercent": memory_used,
        "memoryTotalBytes": item.memory_total_bytes,
        "memoryAvailableBytes": item.memory_available_bytes,
        "swapTotalBytes": item.swap_total_bytes,
        "swapFreeBytes": item.swap_free_bytes,
        "diskUsedPercent": disk_used,
        "diskTotalBytes": item.disk_total_bytes,
        "diskAvailableBytes": item.disk_available_bytes,
        "networkTxBps": item.network_tx_bps,
        "networkRxBps": item.network_rx_bps,
        "diskReadBps": item.disk_read_bps,
        "diskWriteBps": item.disk_write_bps,
        "diskReadIops": item.disk_read_iops,
        "diskWriteIops": item.disk_write_iops,
        "filesystems": item.filesystems,
        "interface": item.interface,
        "containers": item.containers,
        "workloads": item.workloads,
    }


async def monitoring_summary(db: AsyncSession, hours: int = 24, source: str = "primary") -> dict[str, Any]:
    since = utcnow() - timedelta(hours=max(1, min(hours, 24 * 35)))
    samples = list(
        (
            await db.execute(
                select(ServerMetricSampleModel)
                .where(
                    ServerMetricSampleModel.source == source,
                    ServerMetricSampleModel.captured_at >= since,
                    ServerMetricSampleModel.deleted_at.is_(None),
                )
                .order_by(ServerMetricSampleModel.captured_at)
            )
        )
        .scalars()
        .all()
    )
    step = max(1, len(samples) // 300)
    points = [metric_json(item) for item in samples[::step]]
    latest = samples[-1] if samples else None
    month = _month_start(utcnow())
    traffic = (
        await db.execute(
            select(ServerTrafficMonthModel).where(
                ServerTrafficMonthModel.source == source,
                ServerTrafficMonthModel.month == month,
                ServerTrafficMonthModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    alerts = list(
        (
            await db.execute(
                select(ServerAlertEventModel)
                .where(
                    ServerAlertEventModel.source == source,
                    ServerAlertEventModel.deleted_at.is_(None),
                )
                .order_by(ServerAlertEventModel.last_observed_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    used = traffic.egress_bytes if traffic else 0
    quota = traffic.quota_bytes if traffic else settings.server_traffic_quota_gib * GIB
    return {
        "latest": metric_json(latest) if latest else None,
        "points": points,
        "traffic": {
            "month": month.isoformat(),
            "quotaBytes": quota,
            "egressBytes": used,
            "remainingBytes": max(0, quota - used),
            "usedPercent": _percent(used, quota),
            "accounting": "public-egress",
            "unit": "GiB",
            "reset": "calendar-month",
        },
        "alerts": [
            {
                "id": x.id,
                "key": x.alert_key,
                "severity": x.severity,
                "status": x.status,
                "title": x.title,
                "message": x.message,
                "firstTriggeredAt": x.first_triggered_at.isoformat(),
                "lastObservedAt": x.last_observed_at.isoformat(),
                "resolvedAt": x.resolved_at.isoformat() if x.resolved_at else None,
            }
            for x in alerts
        ],
        "stale": not latest or _aware(latest.captured_at) < utcnow() - timedelta(minutes=5),
    }
