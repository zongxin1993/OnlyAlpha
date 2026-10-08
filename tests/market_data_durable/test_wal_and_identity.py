from __future__ import annotations

import json
import os
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
        assert coordinator.recover_all() == ()
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


def test_preclosure_segment_metadata_rebuilds_recovery_scope_from_immutable_wal(tmp_path: Path, fixed_now) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    metadata_path = tmp_path / f"{segment.segment_id}.segment.json"
    metadata = json.loads(metadata_path.read_text())
    for field in (
        "instrument_id",
        "data_kind",
        "start_ns",
        "end_ns",
        "data_version",
        "bar_type",
        "first_sequence",
        "last_sequence",
    ):
        metadata.pop(field)
    metadata_path.write_text(json.dumps(metadata))

    restored = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now).load_segment(segment.segment_id)
    assert restored.recovery_scope().data_kind == "TRADE"
    assert restored.content_hash == segment.content_hash


@pytest.mark.parametrize("stage", ["W1_METADATA_PREPARED", "W2_WAL_CREATED"])
def test_segment_creation_intermediate_states_have_one_restart_action(tmp_path: Path, fixed_now, stage: str) -> None:
    def barrier(actual: str) -> None:
        if actual == stage:
            raise RuntimeError(stage)

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    with pytest.raises(RuntimeError, match=stage):
        wal.open_segment("creation-crash")

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    assert (
        OnlyMarketDataRecoveryCoordinator(
            restarted, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).recover_all()
        == ()
    )
    assert restarted.scan_open() == ()


def test_non_empty_orphan_open_wal_is_never_discarded(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("orphan")
    ingress.record(observation(), trade_update())
    (tmp_path / "orphan.open.json").unlink()

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    with pytest.raises(OnlyWalCorruptionError, match="WAL_OPEN_METADATA_MISSING"):
        OnlyMarketDataRecoveryCoordinator(
            restarted, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).recover_all()
    assert (tmp_path / "orphan.open.wal").stat().st_size > 0


@pytest.mark.parametrize("stage", ["W6_SEAL_METADATA_PREPARED", "W7_WAL_RENAMED_BEFORE_METADATA"])
def test_seal_interruption_publishes_durable_prepared_metadata(tmp_path: Path, fixed_now, stage: str) -> None:
    fired = False

    def barrier(actual: str) -> None:
        nonlocal fired
        if stage == actual and not fired:
            fired = True
            raise RuntimeError(actual)

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("seal-crash")
    ingress.record(observation(), trade_update())
    with pytest.raises(RuntimeError, match=stage):
        ingress.seal()
    assert wal._sealing_id is None

    restarted = OnlyMarketDataWal(
        tmp_path,
        capacity_bytes=1_000_000,
        now=lambda: fixed_now().replace(year=fixed_now().year + 1),
    )
    if restarted.scan_open():
        segment = restarted.seal_recovered_open("seal-crash")
    else:
        segment = restarted.load_segment("seal-crash")
    assert restarted.verify_sealed(segment)
    assert restarted._sealing_id is None
    assert segment.recovery_scope().data_kind == "TRADE"
    assert segment.sealed_at == fixed_now()


def test_writer_seal_converges_when_recovery_publishes_its_prepared_metadata(tmp_path: Path, fixed_now) -> None:
    def barrier(stage: str) -> None:
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            recovered = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now).load_segment("seal-race")
            assert recovered.record_count == 1

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("seal-race")
    ingress.record(observation(), None)

    segment = ingress.seal()

    assert segment.canonical_count == 0
    assert wal.load_segment(segment.segment_id) == segment
    assert wal.scan_open() == ()
    assert not ingress.segment_open
    ingress.begin_segment("seal-next")
    ingress.record(observation(b'{"e":"trade","t":11}'), trade_update(11))
    assert ingress.seal().segment_id == "seal-next"


@pytest.mark.parametrize("stage", ["W9_GC_MARKED_BEFORE_WAL_MOVE", "W10_GC_WAL_DELETED_BEFORE_METADATA"])
def test_gc_interruption_is_idempotently_completed(tmp_path: Path, fixed_now, stage: str) -> None:
    wal, segment = recorded_segment(tmp_path, fixed_now)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    commit = OnlyRevisionCommitService(store, catalog, now=fixed_now)

    def barrier(actual: str) -> None:
        if actual == stage:
            raise RuntimeError(stage)

    fault_wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    with pytest.raises(RuntimeError, match=stage):
        OnlyMarketDataRecoveryCoordinator(fault_wal, store, catalog, commit).drain(
            segment.segment_id, segment.recovery_scope()
        )

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    result = OnlyMarketDataRecoveryCoordinator(restarted, store, catalog, commit).recover_all()
    assert result in {(), ("ALREADY_COMMITTED",)}
    assert restarted.scan_uncommitted() == ()
    assert restarted.scan_gc_eligible() == ()


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


def test_append_reuses_only_exact_prefix_without_repeating_frame_scans(tmp_path: Path, fixed_now, monkeypatch) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("prefix")
    scans = []
    decoded_frames = []
    syncs = []
    read_frames = wal._read_frames
    decode_frames = wal._decode_frames
    fsync = os.fsync

    def tracked_read(path, *, sealed):
        scans.append((path, sealed))
        yield from read_frames(path, sealed=sealed)

    def tracked_sync(descriptor):
        syncs.append(descriptor)
        fsync(descriptor)

    def tracked_decode(data, *, sealed):
        for frame in decode_frames(data, sealed=sealed):
            decoded_frames.append(frame[0])
            yield frame

    monkeypatch.setattr(wal, "_read_frames", tracked_read)
    monkeypatch.setattr(wal, "_decode_frames", tracked_decode)
    monkeypatch.setattr(os, "fsync", tracked_sync)
    receipts = [ingress.record(observation(), None) for _ in range(128)]

    assert [item.ordinal for item in receipts] == list(range(128))
    assert all(item.durability_state.value == "WAL_DURABLE" for item in receipts)
    assert len(syncs) == 128
    assert scans == []
    assert decoded_frames == []
    segment = ingress.seal()
    assert segment.record_count == 128
    assert scans == [(tmp_path / "prefix.open.wal", False)]
    assert len(decoded_frames) == 128
    assert wal.verify_sealed(segment)
    ingress.begin_segment("next-prefix")
    assert ingress.record(observation(), None).ordinal == 0


@pytest.mark.parametrize("mutation", ["checksum", "ordinal", "torn", "replacement"])
def test_append_does_not_trust_changed_prefix_even_with_same_size_and_mtime(
    tmp_path: Path, fixed_now, mutation: str
) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("changed-prefix")
    ingress.record(observation(), trade_update())
    path = tmp_path / "changed-prefix.open.wal"
    before = path.stat()
    data = bytearray(path.read_bytes())
    if mutation in {"checksum", "replacement"}:
        data[-1] ^= 1
    elif mutation == "ordinal":
        data[20] ^= 1
    else:
        data.extend(b"torn")
    if mutation == "replacement":
        replacement = tmp_path / "replacement.wal"
        replacement.write_bytes(data)
        os.replace(replacement, path)
    else:
        path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(OnlyWalCorruptionError):
        ingress.record(observation(), trade_update(11))
    assert path.read_bytes() == data
    with pytest.raises(OnlyWalCorruptionError):
        ingress.seal()


@pytest.mark.parametrize("stage", ["W4_FRAME_WRITTEN_BEFORE_FSYNC", "W5_FRAME_DURABLE"])
def test_interrupted_append_rederives_ordinal_from_frames(tmp_path: Path, fixed_now, stage: str) -> None:
    fired = False

    def barrier(actual: str) -> None:
        nonlocal fired
        if actual == stage and not fired:
            fired = True
            raise RuntimeError(actual)

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("interrupted-append")
    with pytest.raises(RuntimeError, match=stage):
        ingress.record(observation(), trade_update())
    assert ingress.record(observation(), trade_update(11)).ordinal == 1
    segment = ingress.seal()
    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    assert restarted.load_segment(segment.segment_id) == segment
    assert segment.record_count == 2


def test_exact_prefix_and_full_scan_produce_identical_wal_and_segment(tmp_path: Path, fixed_now) -> None:
    segments = []
    contents = []
    for mode in ("cached", "scanned"):
        root = tmp_path / mode
        wal = OnlyMarketDataWal(root, capacity_bytes=1_000_000, now=fixed_now)
        ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
        ingress.begin_segment("equivalent")
        for ordinal in range(32):
            if mode == "scanned":
                wal._append_prefix = None
            assert ingress.record(observation(), trade_update(ordinal + 10)).ordinal == ordinal
        segments.append(ingress.seal())
        contents.append((root / "equivalent.sealed.wal").read_bytes())
        assert wal.verify_sealed(segments[-1])
    assert contents[0] == contents[1]
    assert segments[0] == segments[1]


def test_interrupted_cache_publication_cannot_reuse_a_stale_ordinal(tmp_path: Path, fixed_now, monkeypatch) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("cache-publication")
    fired = False

    def interrupt_publication(self, name, value):
        nonlocal fired
        object.__setattr__(self, name, value)
        if (
            self is wal
            and not fired
            and ((name == "_append_prefix" and value is not None) or (name == "_append_ordinal" and value == 1))
        ):
            fired = True
            raise RuntimeError("interrupted cache publication")

    with monkeypatch.context() as patch:
        patch.setattr(OnlyMarketDataWal, "__setattr__", interrupt_publication)
        with pytest.raises(RuntimeError, match="interrupted cache publication"):
            ingress.record(observation(), trade_update())
    assert fired
    assert ingress.record(observation(), trade_update(11)).ordinal == 1
    segment = ingress.seal()
    assert segment.record_count == 2
    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    assert restarted.load_segment(segment.segment_id) == segment
    assert restarted.verify_sealed(segment)


def test_fsync_failure_returns_no_receipt_and_restart_uses_only_file_frames(
    tmp_path: Path, fixed_now, monkeypatch
) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("failed-fsync")
    ingress.record(observation(), trade_update())

    def fail_sync(_descriptor):
        raise OSError("injected fsync failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_sync)
        with pytest.raises(OSError, match="injected fsync failure"):
            ingress.record(observation(), trade_update(11))
    assert wal._append_prefix is None
    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    segment = restarted.seal_recovered_open("failed-fsync")
    assert segment.record_count == 2
    assert restarted.verify_sealed(segment)


def test_short_write_never_returns_a_durable_receipt(tmp_path: Path, fixed_now, monkeypatch) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 1)
    ingress.begin_segment("short-write")
    ingress.record(observation(), trade_update())
    path_open = Path.open

    class ShortWriter:
        def __enter__(self):
            self.stream = path_open(tmp_path / "short-write.open.wal", "ab", buffering=0)
            return self

        def write(self, data):
            return self.stream.write(data[:10])

        def fileno(self):
            return self.stream.fileno()

        def __exit__(self, *args):
            self.stream.close()

    def short_open(path, mode="r", *args, **kwargs):
        return ShortWriter() if mode == "ab" else path_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", short_open)
        with pytest.raises(OnlyWalError, match="WAL_FRAME_SHORT_WRITE"):
            ingress.record(observation(), trade_update(11))
    with pytest.raises(OnlyWalCorruptionError, match="TORN_HEADER"):
        ingress.record(observation(), trade_update(12))
    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    recovered = restarted.recover_open("short-write")
    assert recovered.valid_records == 1
    assert recovered.quarantined_tail is not None
    segment = restarted.seal_recovered_open("short-write")
    assert segment.record_count == 1


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
    different_runtime = {**update.to_dict(), "runtime_id": "another-capture-runtime"}
    restarted = OnlyCanonicalMarketFactRecord(
        raw_event_id="raw-restarted",
        provenance=OnlyMarketDataProvenance.REALTIME_STREAM,
        canonical_payload=different_runtime,
        canonical_payload_hash=only_canonical_fingerprint(different_runtime),
        **{key: value for key, value in common.items() if key not in {"canonical_payload", "canonical_payload_hash"}},
    )
    assert len(only_deduplicate_facts((realtime, restarted))) == 1
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
