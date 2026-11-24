"""Aggregate synchronized query shards using the wire send clock and nearest rank."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.mock_video_acceptance import QPS as QPS
from scripts.mock_video_acceptance import SECONDS, pct


def summarize(paths):
    rows = [json.loads(p.read_text()) for p in paths]
    if len({(r["run"], r["start"]) for r in rows}) != 1 or {r["shard"] for r in rows} != set(range(len(rows))):
        raise ValueError("incomplete or mismatched window")
    if any(r.get("shard_count", len(rows)) != len(rows) for r in rows):
        raise ValueError("missing query shard")
    # Older evidence predates target_qps and was recorded at 500 QPS.
    targets = {r.get("target_qps", 500) for r in rows}
    if len(targets) != 1:
        raise ValueError("mismatched target QPS")
    errors = Counter()
    for row in rows:
        errors.update(row["errors"])
    wire = sorted(t for r in rows for t in r["wire_offsets"])
    elapsed = wire[-1] - wire[0] if len(wire) > 1 else 0
    outside = sum(t < 0 or t >= SECONDS * 1000 for t in wire)
    if outside:
        errors["wire send outside 60s window"] = outside
    peaks = {}
    for interval in (100, 1000):
        left = peak = 0
        for right, offset in enumerate(wire):
            while wire[left] <= offset - interval:
                left += 1
            peak = max(peak, right - left + 1)
        peaks[f"{interval}ms"] = peak
    latencies = [v for r in rows for v in r["samples"]]
    return dict(
        run_id=rows[0]["run"],
        start_epoch=rows[0]["start"],
        target_qps=targets.pop(),
        window_s=SECONDS,
        wire_rolling_peaks=peaks,
        sent_in_window=len(wire) - outside,
        sent=len(wire),
        valid_200=len(latencies),
        errors=errors,
        distinct_running_ids=len({jid for r in rows for jid in r["ids"]}),
        send_qps=round((len(wire) - 1) * 1000 / elapsed, 2) if elapsed else 0,
        first_send_ms=wire[0] if wire else None,
        last_send_ms=wire[-1] if wire else None,
        scheduled_to_headers_sent_p95_ms=pct([v for r in rows for v in r["pre_send"]], 0.95),
        sent_to_response_headers_p95_ms=pct([v for r in rows for v in r["headers_wait"]], 0.95),
        p50_ms=pct(latencies, 0.5),
        p95_ms=pct(latencies, 0.95),
        p99_ms=pct(latencies, 0.99),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+", type=Path)
    print(json.dumps(summarize(parser.parse_args().shards)))
