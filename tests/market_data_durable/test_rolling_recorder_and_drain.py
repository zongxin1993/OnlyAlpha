from __future__ import annotations

from onlyalpha.market_data.durable import (
    OnlyDurableMarketDataRecorder,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataDrainService,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)

from .conftest import trade_update
from .test_wal_and_identity import observation


def _components(tmp_path, fixed_now, *, max_records=3, on_sealed=None):
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="normalizer",
        normalizer_version="1",
        ingest_clock_ns=lambda: 1,
    )
    sealed = []
    recorder = OnlyDurableMarketDataRecorder(
        ingress,
        max_records_per_segment=max_records,
        on_sealed=sealed.append if on_sealed is None else on_sealed,
    )
    return wal, recorder, sealed


def test_multiple_same_scope_trades_roll_in_one_finite_segment(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now)
    for _ in range(3):
        recorder(observation(), trade_update())

    assert len(sealed) == 1
    assert sealed[0].record_count == 3
    assert len(wal.read_sealed(sealed[0].segment_id)) == 3


def test_clean_shutdown_seals_tail_and_scope_change_rotates(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=10)
    recorder(observation(), trade_update())
    changed = observation(b'{"e":"trade","t":11}')
    changed = changed.__class__(
        changed.source_id,
        "capture-2",
        changed.provider,
        changed.venue,
        changed.market,
        changed.stream,
        changed.provider_event_type,
        changed.ts_receive_ns,
        changed.payload,
        changed.provider_event_id,
        changed.provider_sequence,
        changed.ts_event_ns,
        changed.payload_codec,
        changed.provider_schema,
        changed.provenance,
    )
    recorder(changed, trade_update())
    recorder.close()

    assert [item.record_count for item in sealed] == [1, 1]
    assert len(wal.scan_uncommitted()) == 2


def test_normal_drain_uses_recovery_authority_and_converges_idempotently(tmp_path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    drain = OnlyMarketDataDrainService(recovery, capacity=1)
    recorder = OnlyDurableMarketDataRecorder(
        OnlyMarketDataIngress(
            wal,
            normalizer_id="normalizer",
            normalizer_version="1",
            ingest_clock_ns=lambda: 1,
        ),
        max_records_per_segment=2,
        on_sealed=drain.submit,
    )

    recorder(observation(), trade_update(10))
    recorder(observation(b'{"e":"trade","t":11}'), trade_update(11))
    assert drain.health().writer_queue_depth == 1
    assert drain.drain_pending() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert wal.scan_uncommitted() == ()
    assert recovery.recover_all() == ()


def test_database_failure_keeps_sealed_wal_for_same_recovery_path(tmp_path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)

    class FailingStore(OnlyInMemoryMarketFactStore):
        unavailable = True

        def write_segment(self, segment, records):
            if self.unavailable:
                raise RuntimeError("database unavailable")
            return super().write_segment(segment, records)

    store = FailingStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    drain = OnlyMarketDataDrainService(recovery)
    recorder = OnlyDurableMarketDataRecorder(
        OnlyMarketDataIngress(
            wal,
            normalizer_id="normalizer",
            normalizer_version="1",
            ingest_clock_ns=lambda: 1,
        ),
        max_records_per_segment=1,
        on_sealed=drain.submit,
    )

    recorder(observation(), trade_update())
    assert drain.drain_pending() == ()
    assert len(wal.scan_uncommitted()) == 1
    assert recovery.health().last_recovery_error == "RuntimeError:database unavailable"
    assert drain.health().recording_state.value == "DEGRADED"

    store.unavailable = False
    assert drain.drain_pending() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert wal.scan_uncommitted() == ()
    assert drain.health().last_recovery_error is None
