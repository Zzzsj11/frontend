from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    ServerAlertEventModel,
    ServerMetricSampleModel,
    ServerTrafficMonthModel,
    utcnow,
)

GIB = 1024**3


def _percent(used: int | float, total: int | float) -> float:
    return round(float(used) / float(total) * 100, 2) if total else 0.0


def _month_start(value: datetime) -> date:
    local = value.astimezone(ZoneInfo(settings.server_monitor_timezone))
    return local.date().replace(day=1)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
        load_1=float(payload.get("load1") or 0),
        load_5=float(payload.get("load5") or 0),
        load_15=float(payload.get("load15") or 0),
        memory_total_bytes=int(payload.get("memoryTotalBytes") or 0),
        memory_available_bytes=int(payload.get("memoryAvailableBytes") or 0),
        disk_total_bytes=int(payload.get("diskTotalBytes") or 0),
        disk_available_bytes=int(payload.get("diskAvailableBytes") or 0),
        network_tx_bytes_total=int(payload.get("networkTxBytesTotal") or 0),
        network_rx_bytes_total=int(payload.get("networkRxBytesTotal") or 0),
        network_tx_bps=float(payload.get("networkTxBps") or 0),
        network_rx_bps=float(payload.get("networkRxBps") or 0),
        containers=list(payload.get("containers") or []),
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
    checks = (
        ("cpu", "CPU 使用率过高", sample.cpu_percent, 80.0, 95.0, "%"),
        ("memory", "可用内存不足", memory_used, 80.0, 90.0, "% 已使用"),
        ("disk", "磁盘空间不足", disk_used, 75.0, 90.0, "% 已使用"),
        ("traffic", "月度公网出站流量接近配额", traffic_used, 70.0, 95.0, "% 已使用"),
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
        "load": [item.load_1, item.load_5, item.load_15],
        "memoryUsedPercent": memory_used,
        "memoryTotalBytes": item.memory_total_bytes,
        "memoryAvailableBytes": item.memory_available_bytes,
        "diskUsedPercent": disk_used,
        "diskTotalBytes": item.disk_total_bytes,
        "diskAvailableBytes": item.disk_available_bytes,
        "networkTxBps": item.network_tx_bps,
        "networkRxBps": item.network_rx_bps,
        "interface": item.interface,
        "containers": item.containers,
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
