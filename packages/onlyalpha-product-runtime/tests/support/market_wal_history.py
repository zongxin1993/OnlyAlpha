"""Regenerate/check deterministic bytes from the canonical Python WAL writer.

This storage reference is a test tool, never a Product or algorithm-worker path.
"""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.market_data.durable.codec import only_encode_record_bundle
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from tests.market_data_durable.conftest import BAR_CONSTRUCTION, BASE, SOURCE, bar_update


def generate() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="onlyalpha-market-wal-reference-") as temporary:
        root = Path(temporary)
        wal = OnlyMarketDataWal(root, capacity_bytes=1_000_000, now=lambda: BASE + timedelta(hours=2))
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id="fixture",
            normalizer_version="1",
            ingest_clock_ns=lambda: 123,
            bar_construction=BAR_CONSTRUCTION,
        )
        ingress.begin_segment("python-history")
        observation = OnlyRawProviderObservation(
            str(SOURCE),
            "capture",
            "BINANCE",
            "BINANCE",
            "SPOT",
            "/api/v3/klines",
            "klines",
            int((BASE + timedelta(hours=1)).timestamp() * 1_000_000_000),
            b'{"controlled_storage_fixture":true}',
            provenance="REST_BACKFILL",
        )
        ingress.record(observation, bar_update())
        segment = ingress.seal()
        metadata_path = root / "python-history.segment.json"
        original = metadata_path.read_text()
        legacy = json.loads(original)
        for key in ("instrument_id", "data_kind", "start_ns", "end_ns", "data_version", "bar_type"):
            legacy.pop(key)
        legacy_text = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
        metadata_path.write_text(legacy_text)
        assert wal.load_segment("python-history") == segment
        [bundle] = wal.read_sealed("python-history")
        bundle = replace(
            bundle, canonical_facts=tuple(replace(fact, segment_id="test-write") for fact in bundle.canonical_facts)
        )
        native_bundle = only_encode_record_bundle(bundle).decode()
        reference = OnlyMarketDataWal(
            root, capacity_bytes=1_000_000, now=lambda: datetime.fromisoformat("2026-10-22T00:00:00+00:00")
        )
        reference.open_segment("test-write")
        reference.append(bundle)
        native_metadata = reference.seal(sealed_at=datetime.fromisoformat("2026-10-22T03:00:00+00:00"))
        assert reference.load_segment("test-write") == native_metadata
        assert reference.read_sealed("test-write") == (bundle,)
        return {
            "schema_version": 1,
            "original_metadata_json": original,
            "legacy_metadata_json": legacy_text,
            "sealed_wal_base64": base64.b64encode((root / "python-history.sealed.wal").read_bytes()).decode(),
            "native_bundle_json": native_bundle,
            "native_metadata_json": (root / "test-write.segment.json").read_text(),
            "native_wal_base64": base64.b64encode((root / "test-write.sealed.wal").read_bytes()).decode(),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "check"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    expected = json.dumps(generate(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.mode == "write":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(expected)
    elif args.path.read_text() != expected:
        raise ValueError("MARKET_WAL_REFERENCE_BYTES_CHANGED")


if __name__ == "__main__":
    main()
