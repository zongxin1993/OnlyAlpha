from __future__ import annotations

import threading

import pytest

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


def test_owned_worker_stops_idempotently_and_cannot_restart(tmp_path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    drain = OnlyMarketDataDrainService(recovery, stop_timeout_seconds=1)

    drain.start()
    worker = drain._worker
    assert worker is not None and worker.is_alive()
    assert not worker.daemon

    drain.stop()
    drain.stop()
    drain.stop()

    assert not worker.is_alive()
    assert drain._worker is None
    with pytest.raises(RuntimeError, match="MARKET_DATA_DRAIN_RESTART_FORBIDDEN"):
        drain.start()


def test_blocked_recovery_times_out_without_false_stop_or_concurrent_fallback(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    delegate = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )

    class BlockingRecovery:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()
            self._lock = threading.Lock()
            self.active = 0
            self.maximum_active = 0
            self.calls = 0

        def recover_all(self, *, should_continue=None):
            with self._lock:
                self.calls += 1
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            self.entered.set()
            self.release.wait()
            with self._lock:
                self.active -= 1
            return ()

        def health(self):
            return delegate.health()

    recovery = BlockingRecovery()
    drain = OnlyMarketDataDrainService(recovery, stop_timeout_seconds=0.01)  # type: ignore[arg-type]
    drain.start()
    drain.submit(sealed[0])
    assert recovery.entered.wait(timeout=1)
    worker = drain._worker
    assert worker is not None

    try:
        with pytest.raises(RuntimeError, match="MARKET_DATA_DRAIN_STOP_TIMEOUT"):
            drain.stop()
        assert drain._worker is worker
        assert worker.is_alive()
        assert drain.health().last_recovery_error == "MARKET_DATA_DRAIN_STOP_TIMEOUT"
        with pytest.raises(RuntimeError, match="MARKET_DATA_DRAIN_CONCURRENT_RECOVERY_FORBIDDEN"):
            drain.drain_pending()
        with pytest.raises(RuntimeError, match="MARKET_DATA_DRAIN_RESTART_FORBIDDEN"):
            drain.start()
        assert recovery.calls == 1
        assert recovery.maximum_active == 1
    finally:
        recovery.release.set()
        worker.join(timeout=1)
        drain.stop()

    assert drain._worker is None
    assert recovery.maximum_active == 1


def test_clean_shutdown_leaves_failed_database_tail_for_fresh_recovery(tmp_path, fixed_now) -> None:
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
    drain = OnlyMarketDataDrainService(recovery, stop_timeout_seconds=1)
    recorder = OnlyDurableMarketDataRecorder(
        OnlyMarketDataIngress(
            wal,
            normalizer_id="normalizer",
            normalizer_version="1",
            ingest_clock_ns=lambda: 1,
        ),
        max_records_per_segment=10,
        on_sealed=drain.submit,
        on_start=drain.start,
        on_close=drain.stop,
    )

    recorder.start()
    recorder(observation(), trade_update())
    recorder.close()

    assert len(wal.scan_uncommitted()) == 1
    [segment_id] = wal.scan_uncommitted()
    segment = wal.load_segment(segment_id)
    assert not catalog.is_segment_committed(segment.segment_id, segment.content_hash)

    store.unavailable = False
    restarted_wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)
    restarted = OnlyMarketDataRecoveryCoordinator(
        restarted_wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    assert restarted.recover_all() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert restarted_wal.scan_uncommitted() == ()
    assert restarted.recover_all() == ()


def test_queue_pressure_cannot_hide_sealed_wal_from_recovery(tmp_path, fixed_now) -> None:
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
        max_records_per_segment=1,
        on_sealed=drain.submit,
    )

    for sequence in (10, 11, 12):
        recorder(observation(f'{{"e":"trade","t":{sequence}}}'.encode()), trade_update(sequence))

    assert len(wal.scan_uncommitted()) == 3
    assert drain.health().last_recovery_error == "MARKET_DATA_DRAIN_QUEUE_FULL"
    assert drain.drain_pending() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert wal.scan_uncommitted() == ()
    assert recovery.recover_all() == ()


def test_stop_finishes_current_bounded_unit_and_leaves_remaining_backlog(tmp_path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)

    class PausingStore(OnlyInMemoryMarketFactStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
            self._pause_once = True

        def write_segment(self, segment, records):
            result = super().write_segment(segment, records)
            if self._pause_once:
                self._pause_once = False
                self.entered.set()
                self.release.wait()
            return result

    store = PausingStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal,
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    drain = OnlyMarketDataDrainService(recovery, capacity=4, stop_timeout_seconds=1)
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
    for sequence in (10, 11, 12):
        recorder(observation(f'{{"e":"trade","t":{sequence}}}'.encode()), trade_update(sequence))

    drain.start()
    assert store.entered.wait(timeout=1)
    stop_completed = threading.Event()
    stop_failure: list[BaseException] = []

    def stop_drain() -> None:
        try:
            drain.stop()
        except BaseException as exc:
            stop_failure.append(exc)
        finally:
            stop_completed.set()

    stopper = threading.Thread(target=stop_drain)
    stopper.start()
    assert drain._stop.wait(timeout=1)
    store.release.set()
    assert stop_completed.wait(timeout=1)
    stopper.join(timeout=1)

    assert stop_failure == []
    assert len(wal.scan_uncommitted()) == 3
    restarted = OnlyMarketDataRecoveryCoordinator(
        OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now),
        store,
        catalog,
        OnlyRevisionCommitService(store, catalog, now=fixed_now),
    )
    assert restarted.recover_all() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert wal.scan_uncommitted() == ()
