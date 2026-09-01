"""Bounded normal-operation drain using the crash-recovery authority."""

from __future__ import annotations

import queue
import threading
from enum import StrEnum

from .models import OnlyIngestSegment, OnlyMarketDataHealth, OnlyRecordingState
from .recovery import OnlyMarketDataRecoveryCoordinator

_STOP_JOIN_TIMEOUT_SECONDS = 30.0
_WAKE = object()


class _OnlyDrainLifecycle(StrEnum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED_STOP = "FAILED_STOP"


class OnlyMarketDataDrainService:
    """One bounded worker; restart recovery and normal drain share semantics."""

    def __init__(
        self,
        recovery: OnlyMarketDataRecoveryCoordinator,
        *,
        capacity: int = 128,
        stop_timeout_seconds: float = _STOP_JOIN_TIMEOUT_SECONDS,
    ) -> None:
        if capacity <= 0:
            raise ValueError("MARKET_DATA_DRAIN_CAPACITY_INVALID")
        if stop_timeout_seconds <= 0:
            raise ValueError("MARKET_DATA_DRAIN_STOP_TIMEOUT_INVALID")
        self._recovery = recovery
        self._queue: queue.Queue[OnlyIngestSegment | object] = queue.Queue(capacity)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._lifecycle = _OnlyDrainLifecycle.NEW
        self._synchronous_drain_active = False
        self._stop_timeout_seconds = stop_timeout_seconds
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._lifecycle is _OnlyDrainLifecycle.RUNNING:
                return
            if self._synchronous_drain_active:
                raise RuntimeError("MARKET_DATA_DRAIN_CONCURRENT_RECOVERY_FORBIDDEN")
            if self._lifecycle is not _OnlyDrainLifecycle.NEW:
                raise RuntimeError("MARKET_DATA_DRAIN_RESTART_FORBIDDEN")
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, name="market-data-durable-drain")
            self._lifecycle = _OnlyDrainLifecycle.RUNNING
            self._worker.start()

    def submit(self, segment: OnlyIngestSegment) -> None:
        try:
            self._queue.put_nowait(segment)
        except queue.Full:
            # The sealed WAL remains authoritative and recover_all() will find it.
            # Explicit health/backlog exposes that normal drain is degraded.
            with self._lock:
                self._last_error = "MARKET_DATA_DRAIN_QUEUE_FULL"
            return

    def drain_pending(self) -> tuple[str, ...]:
        """Deterministic non-threaded helper, legal only without a live worker."""

        with self._lock:
            worker = self._worker
            if self._synchronous_drain_active or (worker is not None and worker.is_alive()):
                raise RuntimeError("MARKET_DATA_DRAIN_CONCURRENT_RECOVERY_FORBIDDEN")
            self._synchronous_drain_active = True

        try:
            results: list[str] = []
            pending = self._queue.qsize()
            for _ in range(pending):
                try:
                    segment = self._queue.get_nowait()
                except queue.Empty:
                    break
                if segment is _WAKE:
                    self._queue.task_done()
                    continue
                try:
                    results.extend(self._recovery.recover_all())
                    with self._lock:
                        self._last_error = None
                except Exception as exc:
                    # Sealed WAL remains discoverable by the same coordinator.
                    with self._lock:
                        self._last_error = f"{type(exc).__name__}:{exc}"
                    try:
                        self._queue.put_nowait(segment)
                    except queue.Full:
                        with self._lock:
                            self._last_error = "MARKET_DATA_DRAIN_QUEUE_FULL"
                    break
                finally:
                    self._queue.task_done()
            return tuple(results)
        finally:
            with self._lock:
                self._synchronous_drain_active = False

    def stop(self) -> None:
        with self._lock:
            worker = self._worker
            if worker is None:
                self._lifecycle = _OnlyDrainLifecycle.STOPPED
                return
            self._lifecycle = _OnlyDrainLifecycle.STOPPING
            self._stop.set()
        try:
            self._queue.put_nowait(_WAKE)
        except queue.Full:
            pass
        worker.join(timeout=self._stop_timeout_seconds)
        with self._lock:
            if worker.is_alive():
                self._lifecycle = _OnlyDrainLifecycle.FAILED_STOP
                self._last_error = "MARKET_DATA_DRAIN_STOP_TIMEOUT"
                raise RuntimeError("MARKET_DATA_DRAIN_STOP_TIMEOUT")
            if self._worker is worker:
                self._worker = None
            self._lifecycle = _OnlyDrainLifecycle.STOPPED
            if self._last_error == "MARKET_DATA_DRAIN_STOP_TIMEOUT":
                self._last_error = None

    def health(self) -> OnlyMarketDataHealth:
        base = self._recovery.health()
        with self._lock:
            last_error = self._last_error
        return OnlyMarketDataHealth(
            OnlyRecordingState.DEGRADED if last_error is not None else base.recording_state,
            base.wal_bytes_used,
            base.wal_capacity,
            base.open_segments,
            base.sealed_uncommitted_segments,
            base.oldest_uncommitted_age,
            self._queue.qsize(),
            base.last_verified_segment,
            base.last_committed_segment,
            base.recovery_count,
            last_error or base.last_recovery_error,
            base.coverage_revision_lag,
            base.clickhouse_write_latency_seconds,
            base.postgres_commit_latency_seconds,
            base.postgres_commit_errors,
        )

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    segment = self._queue.get()
                except queue.Empty:  # pragma: no cover - blocking get cannot raise this
                    continue
                try:
                    if segment is _WAKE or self._stop.is_set():
                        continue
                    self._recovery.recover_all(should_continue=lambda: not self._stop.is_set())
                    with self._lock:
                        if self._lifecycle is _OnlyDrainLifecycle.RUNNING:
                            self._last_error = None
                except Exception as exc:
                    # Do not delete or acknowledge the sealed WAL. Recovery owns retry.
                    with self._lock:
                        if self._lifecycle is not _OnlyDrainLifecycle.FAILED_STOP:
                            self._last_error = f"{type(exc).__name__}:{exc}"
                    if not self._stop.is_set():
                        try:
                            self._queue.put_nowait(segment)
                        except queue.Full:
                            with self._lock:
                                self._last_error = "MARKET_DATA_DRAIN_QUEUE_FULL"
                        self._stop.wait(0.25)
                finally:
                    self._queue.task_done()
        finally:
            with self._lock:
                if self._worker is threading.current_thread():
                    if self._stop.is_set():
                        self._lifecycle = _OnlyDrainLifecycle.STOPPED
                    else:
                        self._lifecycle = _OnlyDrainLifecycle.FAILED_STOP
                        self._last_error = self._last_error or "MARKET_DATA_DRAIN_WORKER_FAILED"


__all__ = ["OnlyMarketDataDrainService"]
