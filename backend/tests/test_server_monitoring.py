from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import session_factory
from app.models import ServerAlertEventModel, ServerMetricSampleModel, ServerTrafficMonthModel
from app.server_monitoring import GIB, ingest_server_metric


def payload(captured: datetime, *, tx: int, cpu: float = 10) -> dict:
    return {
        "source": "primary",
        "capturedAt": captured.isoformat(),
        "bootId": "boot-test",
        "interface": "eth0",
        "cpuPercent": cpu,
        "cpuIowaitPercent": 2.5,
        "load1": 0.1,
        "load5": 0.2,
        "load15": 0.3,
        "memoryTotalBytes": 8 * GIB,
        "memoryAvailableBytes": 4 * GIB,
        "swapTotalBytes": 4 * GIB,
        "swapFreeBytes": 3 * GIB,
        "diskTotalBytes": 100 * GIB,
        "diskAvailableBytes": 50 * GIB,
        "networkTxBytesTotal": tx,
        "networkRxBytesTotal": tx * 2,
        "networkTxBps": 1024,
        "networkRxBps": 2048,
        "diskReadBps": 4096,
        "diskWriteBps": 8192,
        "diskReadIops": 2,
        "diskWriteIops": 4,
        "filesystems": [{"path": "/", "totalBytes": 100 * GIB, "availableBytes": 50 * GIB, "inodeTotal": 1000, "inodeFree": 900}],
        "containers": [{"name": "backend", "cpuPercent": 1.2, "memoryPercent": 3.4}],
    }


def test_metric_ingest_tracks_egress_and_alerts(client):
    async def run():
        async with session_factory() as db:
            for model in (ServerAlertEventModel, ServerTrafficMonthModel, ServerMetricSampleModel):
                await db.execute(delete(model))
            await db.commit()
            now = datetime.now(timezone.utc)
            await ingest_server_metric(db, payload(now - timedelta(minutes=1), tx=10 * GIB))
            await ingest_server_metric(db, payload(now, tx=11 * GIB, cpu=96))
            traffic = (await db.execute(select(ServerTrafficMonthModel))).scalar_one()
            alerts = list((await db.execute(select(ServerAlertEventModel))).scalars())
            assert traffic.egress_bytes == GIB
            assert traffic.quota_bytes == 300 * GIB
            assert any(item.alert_key == "cpu" and item.severity == "critical" for item in alerts)

    asyncio.run(run())
    response = client.get("/api/admin/server-monitoring?hours=1")
    assert response.status_code == 200
    body = response.json()
    assert body["latest"]["interface"] == "eth0"
    assert body["latest"]["cpuIowaitPercent"] == 2.5
    assert body["latest"]["workloads"]["configuredExecutionLimits"]["export"] == 1
    assert body["traffic"]["accounting"] == "public-egress"
    assert body["traffic"]["quotaBytes"] == 300 * GIB


def test_maintenance_is_dry_run_only(client):
    response = client.post(
        "/api/admin/server-monitoring/maintenance/dry-run",
        json={"action": "cleanup_temp_files"},
    )
    assert response.status_code == 201
    assert response.json()["dryRun"] is True
    assert "DRY-RUN" in response.json()["summary"]
    assert client.post("/api/admin/server-monitoring/maintenance/dry-run", json={"action": "unsafe_delete"}).status_code == 422
