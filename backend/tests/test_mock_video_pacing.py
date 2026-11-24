import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import mock_video_query_shard as shard
from scripts.mock_video_window import summarize


def test_dispatch_misses_are_counted_once():
    budget = shard.WirePacer(4, 60).credit
    assert shard.skip_reason(budget + 0.001, 96, budget) == "scheduler_late"
    assert shard.skip_reason(budget, 96, budget) == "pending_limit"
    assert shard.skip_reason(0.082, 95, budget) is None


async def test_queued_connections_cannot_burst_or_send_after_window(monkeypatch):
    # All three connections become ready 90 ms late at the same time.
    now = 10.090
    end = now + 0.0075
    pacer = shard.WirePacer(4, end)

    async def sleep(delay):
        nonlocal now
        now += delay

    monkeypatch.setattr(shard, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(shard, "asyncio", SimpleNamespace(sleep=sleep))
    released = []

    async def release(due):
        await pacer.wait(due)
        released.append(now)

    results = await asyncio.gather(*(release(due) for due in (10, 10.04, 10.08)), return_exceptions=True)
    assert results[:2] == [None, None]
    assert isinstance(results[2], shard.WindowClosed)
    assert released[1] - released[0] == pytest.approx(pacer.min_gap)


async def test_recovery_credit_bounds_aggregate_burst(monkeypatch):
    now = 20.0
    pacer = shard.WirePacer(4, now + shard.SECONDS)
    releases = []

    async def sleep(delay):
        nonlocal now
        now += delay

    monkeypatch.setattr(shard, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(shard, "asyncio", SimpleNamespace(sleep=sleep))
    for _ in range(140):
        await pacer.wait(19)
        releases.append(now)
    # Six immediate credits per shard, then one permit per recovery interval.
    for i, sent in enumerate(releases[6:], 6):
        assert sent >= 20 + (i - 5) * pacer.recovery_interval - 1e-9


def test_aggregate_timing_uses_half_open_windows_and_reads_legacy_shards(tmp_path):
    paths = []
    for i, wire in enumerate(([0, 1000, 60000], [99, 100, 59999.999])):
        path = tmp_path / f"shard-{i}.json"
        row = dict(shard=i, run="test", start=100, wire_offsets=wire, samples=[], ids=[], pre_send=[], headers_wait=[], errors={"schedule overrun": i})
        path.write_text(json.dumps(row))
        paths.append(path)
    result = summarize(paths)
    assert result["wire_rolling_peaks"] == {"100ms": 2, "1000ms": 3}
    assert result["target_qps"] == 500
    assert result["sent_in_window"] == 5
    assert result["errors"] == {"schedule overrun": 1, "wire send outside 60s window": 1}
    row.update(shard_count=4)
    paths[1].write_text(json.dumps(row))
    with pytest.raises(ValueError, match="missing query shard"):
        summarize(paths)


def test_current_window_reports_100_qps_without_relabelling_old_shards(tmp_path):
    assert shard.QPS == 100 and shard.QPS * shard.SECONDS == 6000
    paths = [tmp_path / f"shard-{i}.json" for i in range(2)]
    for i, path in enumerate(paths):
        path.write_text(json.dumps(dict(shard=i, run="test", start=100, target_qps=shard.QPS, wire_offsets=[], samples=[], ids=[], pre_send=[], headers_wait=[], errors={})))
    assert summarize(paths)["target_qps"] == 100
    old = json.loads(paths[0].read_text())
    del old["target_qps"]
    paths[0].write_text(json.dumps(old))
    with pytest.raises(ValueError, match="mismatched target QPS"):
        summarize(paths)


async def test_status_request_carries_batch_task_and_gateway_correlation():
    import httpx

    from scripts.mock_video_acceptance import trace_hooks

    rows = []

    def respond(req):
        assert req.headers["X-Agent-Name"] == "code-agent"
        assert req.headers["X-Test-Run-Id"] == "batch"
        assert req.headers["X-Agent-Run-Id"] == "batch-job-123"
        return httpx.Response(200, headers={"X-Request-Id": "rid"})

    async with httpx.AsyncClient(event_hooks=trace_hooks("batch", rows.append), transport=httpx.MockTransport(respond)) as client:
        await client.get("https://example.invalid/v1/jobs/job-123")
    assert rows == [("batch-job-123", 200, "rid")]


def test_production_full_run_requires_matching_environment_and_isolation(monkeypatch):
    from scripts import mock_video_acceptance as proof

    host = "https://mg.epaipix.com"
    monkeypatch.setattr(proof, "HOST", host)
    monkeypatch.setattr(proof, "TIER", "production")
    monkeypatch.setattr(proof, "settings", SimpleNamespace(all_in_one_base_url=host, all_in_one_system_key=False))
    monkeypatch.setenv("TLS_DOMAIN", "mv.epaipix.com")
    monkeypatch.setenv("DEPLOYMENT_TIER", "production")
    monkeypatch.setenv("MV_EXPECTED_ISOLATION", "isolated")
    monkeypatch.delenv("MV_PROOF_ROUTE_VERIFIED", raising=False)
    with pytest.raises(ValueError, match="isolation"):
        proof.check_target()
    monkeypatch.setenv("MV_PROOF_ROUTE_VERIFIED", "isolated")
    proof.check_target()
    monkeypatch.setenv("TLS_DOMAIN", "mv-test.epaipix.com")
    with pytest.raises(ValueError, match="must match"):
        proof.check_target()
