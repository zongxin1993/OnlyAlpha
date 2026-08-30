from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.market_data.durable import (
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataConflictError,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
    OnlyWalCapacityError,
    OnlyWalCorruptionError,
    OnlyWalError,
    only_deduplicate_facts,
)

from .conftest import BASE, trade_update


def observation(payload: bytes = b'{"e":"trade","t":10}') -> OnlyRawProviderObservation:
    return OnlyRawProviderObservation(
        "BINANCE_SPOT",
        "capture-1",
        "BINANCE",
        "BINANCE",
        "SPOT",
        "trade",
        "trade",
        int(BASE.timestamp() * 1_000_000_000),
        payload,
        "10",
        10,
        int(BASE.timestamp() * 1_000_000_000),
        provenance="REALTIME_STREAM",
    )


def recorded_segment(root: Path, fixed_now):
    wal = OnlyMarketDataWal(root, capacity_bytes=1_000_000, now=fixed_now, identity_factory=lambda: "segment-1")
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 123
    )
    ingress.begin_segment()
    ingress.record(observation(), trade_update())
    return wal, ingress.seal()


def test_raw_canonical_wal_round_trip_and_exact_hash(tmp_path: Path, fixed_now) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    assert wal.verify_sealed(segment)
    [bundle] = wal.read_sealed(segment.segment_id)
    assert bundle.evidence.payload == b'{"e":"trade","t":10}'
    assert bundle.evidence.raw_event_id == bundle.canonical_facts[0].raw_event_id
    assert bundle.canonical_facts[0].canonical_fact_id == str(trade_update().update_id)
    assert wal.load_segment(segment.segment_id) == segment


def test_torn_open_tail_is_quarantined_without_losing_complete_record(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    segment_id = ingress.begin_segment("open-segment")
    ingress.record(observation(), trade_update())
    path = tmp_path / "open-segment.open.wal"
    with path.open("ab") as stream:
        stream.write(b"torn")
    result = wal.recover_open(segment_id)
    assert result.valid_records == 1
    assert result.quarantined_tail is not None and result.quarantined_tail.read_bytes() == b"torn"


def test_restart_recovers_and_seals_durable_open_segment(tmp_path: Path, fixed_now) -> None:
    first = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(first, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    segment_id = ingress.begin_segment("restart-open")
    ingress.record(observation(), trade_update())

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    assert restarted.scan_open() == (segment_id,)
    segment = restarted.seal_recovered_open(segment_id)

    assert restarted.scan_open() == ()
    assert restarted.load_segment(segment_id) == segment
    assert restarted.verify_sealed(segment)


@pytest.mark.parametrize("boundary,expected_open", [("C1", False), ("C2", True)])
def test_ingress_crash_boundary_declares_exact_wal_acceptance(
    tmp_path: Path, fixed_now, boundary: str, expected_open: bool
) -> None:
    fired = False

    def barrier(stage: str) -> None:
        nonlocal fired
        if stage == boundary and not fired:
            fired = True
            raise RuntimeError(f"injected {boundary}")

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="n",
        normalizer_version="1",
        ingest_clock_ns=lambda: 1,
        barrier=barrier,
    )
    ingress.begin_segment("crash-boundary")

    with pytest.raises(RuntimeError, match=f"injected {boundary}"):
        ingress.record(observation(), trade_update())

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    if expected_open:
        recovered = restarted.seal_recovered_open("crash-boundary")
        assert recovered.record_count == 1
    else:
        assert restarted.recover_open("crash-boundary").valid_records == 0
        store = OnlyInMemoryMarketFactStore()
        catalog = OnlyInMemoryMarketDataCatalog()
        coordinator = OnlyMarketDataRecoveryCoordinator(
            restarted, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        )
        assert coordinator.recover_all({}) == ()
        assert restarted.scan_open() == ()
        assert (tmp_path / "crash-boundary.abandoned.wal").exists()
        with pytest.raises(OnlyWalError, match="WAL_SEGMENT_ID_CONFLICT"):
            restarted.open_segment("crash-boundary")


def test_restart_rebuilds_metadata_after_seal_rename_boundary(tmp_path: Path, fixed_now) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    metadata = tmp_path / f"{segment.segment_id}.segment.json"
    open_metadata = tmp_path / f"{segment.segment_id}.open.json"
    open_metadata.write_text('{"created_at":"2026-01-01T01:00:00+00:00","schema_version":1,"segment_id":"segment-1"}')
    metadata.unlink()

    recovered = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now).load_segment(segment.segment_id)

    assert recovered.content_hash == segment.content_hash
    assert metadata.exists()
    assert not open_metadata.exists()


def test_corrupt_sealed_segment_fails_closed(tmp_path: Path, fixed_now) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    path = tmp_path / f"{segment.segment_id}.sealed.wal"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(OnlyWalCorruptionError, match="CHECKSUM"):
        wal.read_sealed(segment.segment_id)


def test_wal_capacity_and_sealed_immutability(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=128, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("small")
    with pytest.raises(OnlyWalCapacityError):
        ingress.record(observation(b"x" * 1000), None)
    assert wal.recording_state.value == "DEGRADED"
    assert wal.health().last_recovery_error == "WAL_CAPACITY_FULL"


def test_gc_eligible_segment_no_longer_consumes_uncommitted_capacity(tmp_path: Path, fixed_now) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    assert wal.bytes_used > 0

    gc_path = wal.mark_gc_eligible(segment.segment_id)

    assert gc_path.exists()
    assert wal.bytes_used == 0
    assert wal.health().sealed_uncommitted_segments == 0
    with pytest.raises(OnlyWalError, match="WAL_SEGMENT_ID_CONFLICT"):
        wal.open_segment(segment.segment_id)


def test_matching_realtime_backfill_facts_deduplicate_but_conflict_blocks() -> None:
    update = trade_update()
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.market_data.durable.models import (
        OnlyCanonicalMarketFactRecord,
        OnlyMarketDataProvenance,
        OnlyMarketDataQualityState,
    )

    common = dict(
        canonical_fact_id=str(update.update_id),
        source_id="BINANCE_SPOT",
        segment_id="s",
        capture_session_id="c",
        data_kind="TRADE",
        instrument_id=str(update.instrument_id),
        ts_event_ns=update.ts_event.unix_nanos,
        ts_receive_ns=1,
        ts_ingest_ns=2,
        canonical_payload=update.to_dict(),
        canonical_payload_hash=only_canonical_fingerprint(update.to_dict()),
        normalizer_id="n",
        normalizer_version="1",
        quality_state=OnlyMarketDataQualityState.VALID,
    )
    realtime = OnlyCanonicalMarketFactRecord(
        raw_event_id="raw-1", provenance=OnlyMarketDataProvenance.REALTIME_STREAM, **common
    )
    backfill = OnlyCanonicalMarketFactRecord(
        raw_event_id="raw-2", provenance=OnlyMarketDataProvenance.REST_BACKFILL, **common
    )
    assert len(only_deduplicate_facts((realtime, backfill))) == 1
    changed_payload = trade_update(price="101.12000000").to_dict()
    conflict = OnlyCanonicalMarketFactRecord(
        raw_event_id="raw-3",
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        canonical_payload=changed_payload,
        canonical_payload_hash=only_canonical_fingerprint(changed_payload),
        **{key: value for key, value in common.items() if key not in {"canonical_payload", "canonical_payload_hash"}},
    )
    with pytest.raises(OnlyMarketDataConflictError):
        only_deduplicate_facts((realtime, conflict))
