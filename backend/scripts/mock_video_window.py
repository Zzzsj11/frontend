"""Aggregate synchronized query shards using the wire send clock and nearest rank."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.mock_video_acceptance import pct


def summarize(paths):
    rows = [json.loads(p.read_text()) for p in paths]
    if len({(r["run"], r["start"]) for r in rows}) != 1 or {r["shard"] for r in rows} != set(range(len(rows))):
        raise ValueError("incomplete or mismatched window")
    errors = Counter()
    for row in rows:
        errors.update(row["errors"])
    wire = sorted(t for r in rows for t in r["wire_offsets"])
    elapsed = wire[-1] - wire[0] if len(wire) > 1 else 0
    if wire and (wire[0] < -1 or wire[-1] >= 60050):
        errors["wire send outside 60s window"] += 1
    latencies = [v for r in rows for v in r["samples"]]
    return dict(
        run_id=rows[0]["run"],
        start_epoch=rows[0]["start"],
        target_qps=500,
        window_s=60,
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
