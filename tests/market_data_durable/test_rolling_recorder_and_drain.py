from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from onlyalpha.market_data.durable import (
    OnlyDurableMarketDataRecorder,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataCrashBoundary,
    OnlyMarketDataDrainService,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRecordingState,
    OnlyRevisionCommitService,
)

from .conftest import trade_update
from .test_wal_and_identity import observation


@pytest.mark.parametrize("canonical", [False, True])
def test_health_cannot_repair_metadata_owned_by_live_seal_publisher(
    tmp_path, fixed_now, monkeypatch, canonical
) -> None:
    publish_entered = threading.Event()
    publish_release = threading.Event()
    writer_finished = threading.Event()
    drain_release = threading.Event()
    failures = []
    prepared_reads = []
    wal, recorder, _ = _components(tmp_path, fixed_now, max_records=1, on_sealed=lambda segment: drain.submit(segment))
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()

    def publication(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            publish_entered.set()
            assert publish_release.wait(5)

    def recovery_barrier(stage):
        if stage is OnlyMarketDataCrashBoundary.C3_SEALED_BEFORE_STORE:
            assert drain_release.wait(5)

    wal._barrier = publication
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now), barrier=recovery_barrier
    )
    drain = OnlyMarketDataDrainService(recovery)
    read_text = Path.read_text

    def publishing_metadata(path, *args, **kwargs):
        if path.name.endswith(".segment.json.tmp"):
            prepared_reads.append(path)
            # The real writer publishes between the observer's exists() and read_text().
            publish_release.set()
            assert writer_finished.wait(5)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", publishing_metadata)

    def write():
        try:
            recorder(observation(), trade_update() if canonical else None)
        except Exception as exc:
            failures.append(exc)
        finally:
            writer_finished.set()

    writer = threading.Thread(target=write)
    drain.start()
    writer.start()
    try:
        assert publish_entered.wait(5)
        health = drain.health()
        assert health.recording_state is OnlyRecordingState.HEALTHY, (
            health.recording_state,
            health.last_recovery_error,
        )
        assert health.last_recovery_error is None
        assert prepared_reads == []
        assert health.sealed_uncommitted_segments == 1
        assert health.wal_bytes_used > 0
        publish_release.set()
        assert writer_finished.wait(5)
        assert not failures
        assert recovery.health().sealed_uncommitted_segments == 1
        drain_release.set()
        drain._queue.join()
        assert wal.scan_uncommitted() == ()
        assert drain.health().recording_state is OnlyRecordingState.HEALTHY
        assert drain.health().last_recovery_error is None
        assert drain._worker is not None and drain._worker.is_alive()
        assert len(catalog._segments) == 1
        assert len(store._raw) == 1
        assert recovery.recover_all() == ()
    finally:
        publish_release.set()
        drain_release.set()
        writer.join(5)
        drain.stop()


def test_live_publication_does_not_exempt_another_segment_from_health_validation(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    corrupted_id = sealed[0].segment_id
    (tmp_path / f"{corrupted_id}.segment.json").write_text("{", encoding="utf-8")

    def during_publication(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            assert wal._sealing_id != corrupted_id
            health = wal.health()
            assert health.recording_state is OnlyRecordingState.FAILED
            assert health.last_recovery_error == "JSONDecodeError"

    wal._barrier = during_publication
    recorder(observation(b"different observation"), trade_update())
    assert wal._sealing_id is None
    assert wal.health().recording_state is OnlyRecordingState.FAILED


@pytest.mark.parametrize(
    "state,error",
    [(OnlyRecordingState.FAILED, "FileNotFoundError"), (OnlyRecordingState.DEGRADED, "WAL_CAPACITY_FULL")],
)
def test_publication_owner_never_clears_prior_failure_state(tmp_path, fixed_now, state, error) -> None:
    wal, recorder, _ = _components(tmp_path, fixed_now, max_records=1)
    wal._recording_state = state
    wal._last_error = error

    def during_publication(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            assert wal.health().recording_state is state
            assert wal.health().last_recovery_error == error

    wal._barrier = during_publication
    recorder(observation(), trade_update())
    assert wal._sealing_id is None
    assert wal.health().recording_state is state
    assert wal.health().last_recovery_error == error


def test_nested_publisher_is_rejected_without_releasing_outer_ownership(tmp_path, fixed_now) -> None:
    wal, recorder, _ = _components(tmp_path, fixed_now, max_records=1)

    def during_publication(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            owner = wal._sealing_id
            with pytest.raises(RuntimeError, match="WAL_SEGMENT_SEAL_ALREADY_ACTIVE"):
                wal.seal()
            assert wal._sealing_id == owner
            assert wal.health().recording_state is OnlyRecordingState.HEALTHY

    wal._barrier = during_publication
    recorder(observation(), trade_update())
    assert wal._sealing_id is None


def test_failed_publication_owner_cannot_hide_malformed_prepared_metadata(tmp_path, fixed_now) -> None:
    wal, recorder, _ = _components(tmp_path, fixed_now, max_records=1)

    def interrupted(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            raise RuntimeError("interrupted publication")

    wal._barrier = interrupted
    with pytest.raises(RuntimeError, match="interrupted publication"):
        recorder(observation(), trade_update())
    assert wal._sealing_id is None
    assert wal._open_id is not None
    (tmp_path / f"{wal._open_id}.segment.json.tmp").write_text("{", encoding="utf-8")
    assert wal.health().recording_state is OnlyRecordingState.FAILED
    assert wal.health().last_recovery_error == "JSONDecodeError"


def test_live_publication_cannot_hide_other_owner_metadata_without_wal(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    orphaned_id = sealed[0].segment_id
    (tmp_path / f"{orphaned_id}.sealed.wal").unlink()

    def during_publication(stage):
        if stage == "W7_WAL_RENAMED_BEFORE_METADATA":
            assert wal._sealing_id != orphaned_id
            health = wal.health()
            assert health.recording_state is OnlyRecordingState.FAILED
            assert health.last_recovery_error == "WAL_STATE_CORRUPT:SEGMENT_METADATA_ONLY"

    wal._barrier = during_publication
    recorder(observation(b"different observation"), trade_update())
    assert wal._sealing_id is None
    assert wal.health().recording_state is OnlyRecordingState.FAILED


@pytest.mark.parametrize("sink_fails", [False, True])
def test_background_drain_preserves_exact_failure_diagnostics(tmp_path, fixed_now, caplog, sink_fails) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    attempted = threading.Event()
    release = threading.Event()
    retried = threading.Event()

    class FailingRecovery:
        def recover_sealed(self, *, should_continue=None):
            if attempted.is_set():
                retried.set()
            attempted.set()
            assert release.wait(5)
            raise RuntimeError("database unavailable")

    logged = threading.Event()

    class FailureSignal(logging.Handler):
        def emit(self, record):
            if record.name == "onlyalpha.market_data.durable.drain":
                logged.set()
                if sink_fails:
                    raise RuntimeError("diagnostic sink unavailable")

    logger = logging.getLogger("onlyalpha.market_data.durable.drain")
    signal = FailureSignal()
    logger.addHandler(signal)
    drain = OnlyMarketDataDrainService(FailingRecovery())  # type: ignore[arg-type]
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            drain.start()
            drain.submit(sealed[0])
            assert attempted.wait(5)
            release.set()
            assert logged.wait(5)
            assert retried.wait(5)
            assert wal.scan_uncommitted() == (sealed[0].segment_id,)
            assert drain._worker is not None and drain._worker.is_alive()
        if not sink_fails:
            message = next(record.getMessage() for record in caplog.records if record.name == logger.name)
            assert sealed[0].segment_id in message
            assert "lifecycle=RUNNING" in message
            assert "RuntimeError:database unavailable" in message
    finally:
        release.set()
        drain.stop()
        logger.removeHandler(signal)


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


@pytest.mark.parametrize("write_stage", ["W2_WAL_CREATED", "W7_WAL_RENAMED_BEFORE_METADATA"])
def test_live_drain_does_not_recover_a_writer_owned_wal(tmp_path, fixed_now, write_stage) -> None:
    drain: OnlyMarketDataDrainService | None = None
    opened = 0

    def barrier(stage: str) -> None:
        nonlocal opened
        if stage == write_stage:
            opened += 1
            if opened == 2:
                assert drain is not None
                assert drain.drain_pending() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now, barrier=barrier)
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
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

    recorder(observation(), trade_update(10))
    recorder(observation(b'{"e":"trade","t":11}'), trade_update(11))

    assert opened == 2
    assert wal.scan_open() == ()
    assert drain.drain_pending() in {("COMMITTED",), ("DURABLE_ONLY:INCOMPLETE",)}
    assert recovery.recover_all() == ()


def test_capacity_check_tolerates_sealed_wal_collected_after_discovery(
    tmp_path, fixed_now, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    sealed_path = tmp_path / f"{sealed[0].segment_id}.sealed.wal"
    original_stat = Path.stat

    def stat(path: Path, *args: object, **kwargs: object) -> object:
        if path == sealed_path:
            sealed_path.unlink()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    assert wal.bytes_used == 0


def test_health_does_not_mark_successfully_collected_seal_as_corrupt(
    tmp_path, fixed_now, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    segment_id = sealed[0].segment_id
    load_segment = wal.load_segment

    def collected(_segment_id: str):
        monkeypatch.setattr(wal, "load_segment", load_segment)
        wal.mark_gc_eligible(segment_id)
        wal.collect_garbage(segment_id)
        raise FileNotFoundError(segment_id)

    monkeypatch.setattr(wal, "load_segment", collected)
    health = wal.health()
    assert health.recording_state is OnlyRecordingState.HEALTHY
    assert health.sealed_uncommitted_segments == 0


def test_health_fails_closed_when_sealed_content_is_missing_but_metadata_remains(tmp_path, fixed_now) -> None:
    wal, recorder, sealed = _components(tmp_path, fixed_now, max_records=1)
    recorder(observation(), trade_update())
    (tmp_path / f"{sealed[0].segment_id}.sealed.wal").unlink()

    assert wal.health().recording_state is OnlyRecordingState.FAILED


def test_database_failure_keeps_sealed_wal_for_same_recovery_path(tmp_path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=fixed_now)

    class FailingStore(OnlyInMemoryMarketFactStore):
        unavailable = True

        def write_segments(self, segments, records_by_segment):
            if self.unavailable:
                raise RuntimeError("database unavailable")
            return super().write_segments(segments, records_by_segment)

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

        def recover_sealed(self, *, should_continue=None):
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

        def write_segments(self, segments, records_by_segment):
            if self.unavailable:
                raise RuntimeError("database unavailable")
            return super().write_segments(segments, records_by_segment)

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

        def write_segments(self, segments, records_by_segment):
            result = super().write_segments(segments, records_by_segment)
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
