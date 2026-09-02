"""Standalone fake worker used by subprocess contract tests."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from onlyalpha_plugin_miniqmt.historical_worker.models import OnlyMiniQmtWorkerRequest
from onlyalpha_plugin_miniqmt.historical_worker.protocol import (
    PROTOCOL_VERSION,
    atomic_write_bytes,
    atomic_write_json,
    bars_payload,
    bytes_fingerprint,
    fingerprint,
    read_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--behavior", choices=("success", "opening-boundary", "half", "sleep"), default="success")
    args = parser.parse_args()
    request = OnlyMiniQmtWorkerRequest.parse(read_json(args.request))
    root = args.request.parent
    if args.behavior == "sleep":
        (root / "worker.pid").write_text(str(os.getpid()), encoding="ascii")
        time.sleep(60)
        return 0
    if args.behavior == "opening-boundary":
        minute_ns = 60_000_000_000
        previous_close = request.end_time_ns - (18 * 60 + 36) * minute_ns
        ends = [previous_close - offset * minute_ns for offset in range(5, -1, -1)]
        ends += [request.end_time_ns - 6 * minute_ns]
        ends += [request.end_time_ns - offset * minute_ns for offset in range(5, -1, -1)]
    else:
        ends = [
            request.end_time_ns - (request.required_bars - index - 1) * 60_000_000_000
            for index in range(request.required_bars)
        ]
    records = tuple(
        {
            "instrument_id": request.instrument_id,
            "bar_type": request.period,
            "bar_start_ns": end_ns - 60_000_000_000,
            "bar_end_ns": end_ns,
            "ts_event_ns": end_ns,
            "open": "10.00",
            "high": "10.10",
            "low": "9.90",
            "close": "10.05",
            "volume": "100",
        }
        for end_ns in ends
    )
    encoded = bars_payload(records)
    if args.behavior == "half":
        (root / ".bars.jsonl.tmp").write_bytes(encoded)
        return 0
    atomic_write_bytes(root / "bars.jsonl", encoded)
    atomic_write_json(
        root / "result.json",
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "status": "SUCCESS",
            "provider": "miniqmt",
            "provider_version": "fake-1",
            "compatibility_profile_id": request.compatibility_profile_id,
            "instrument_id": request.instrument_id,
            "period": request.period,
            "requested_bars": request.required_bars,
            "requested_start_ns": request.requested_start_ns,
            "requested_end_ns": request.end_time_ns,
            "bootstrap_observed_at_ns": request.bootstrap_observed_at_ns,
            "provider_raw_bar_count": len(records),
            "accepted_bar_count": len(records),
            "rejected_out_of_range_count": 0,
            "provider_raw_last_bar_end_ns": records[-1]["bar_end_ns"],
            "accepted_last_bar_end_ns": records[-1]["bar_end_ns"],
            "row_count": len(records),
            "first_bar_end_ns": records[0]["bar_end_ns"],
            "last_bar_end_ns": records[-1]["bar_end_ns"],
            "request_fingerprint": request.request_fingerprint,
            "content_fingerprint": fingerprint(records),
            "bars_file_fingerprint": bytes_fingerprint(encoded),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
