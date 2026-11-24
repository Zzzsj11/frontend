import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import mock_video_query_shard as shard
from scripts.mock_video_window import summarize


def test_dispatch_misses_are_counted_once():
    assert shard.skip_reason(0.051, 96) == "scheduler_late"
    assert shard.skip_reason(0.050, 96) == "pending_limit"
    assert shard.skip_reason(0.050, 95) is None


async def test_queued_connections_cannot_burst_or_send_after_window(monkeypatch):
    # All three connections become ready 30 ms late at the same time.
    now = 10.030
    end = now + 0.012
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

    results = await asyncio.gather(*(release(due) for due in (10, 10.008, 10.016)), return_exceptions=True)
    assert results[:2] == [None, None]
    assert isinstance(results[2], shard.WindowClosed)
    assert released[1] - released[0] == pytest.approx(pacer.min_gap)


def test_aggregate_timing_uses_half_open_windows_and_reads_legacy_shards(tmp_path):
    paths = []
    for i, wire in enumerate(([0, 1000, 60000], [99, 100, 59999.999])):
        path = tmp_path / f"shard-{i}.json"
        row = dict(shard=i, run="test", start=100, wire_offsets=wire, samples=[], ids=[], pre_send=[], headers_wait=[], errors={"schedule overrun": i})
        path.write_text(json.dumps(row))
        paths.append(path)
    result = summarize(paths)
    assert result["wire_rolling_peaks"] == {"100ms": 2, "1000ms": 3}
    assert result["sent_in_window"] == 5
    assert result["errors"] == {"schedule overrun": 1, "wire send outside 60s window": 1}
    row.update(shard_count=4)
    paths[1].write_text(json.dumps(row))
    with pytest.raises(ValueError, match="missing query shard"):
        summarize(paths)
