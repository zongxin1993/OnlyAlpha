"""Bounded normal-operation drain using the crash-recovery authority."""

from __future__ import annotations

import queue
import threading

from .models import OnlyIngestSegment, OnlyMarketDataHealth, OnlyRecordingState
from .recovery import OnlyMarketDataRecoveryCoordinator


class OnlyMarketDataDrainService:
    """One bounded worker; restart recovery and normal drain share semantics."""

    def __init__(self, recovery: OnlyMarketDataRecoveryCoordinator, *, capacity: int = 128) -> None:
        if capacity <= 0:
            raise ValueError("MARKET_DATA_DRAIN_CAPACITY_INVALID")
        self._recovery = recovery
        self._queue: queue.Queue[OnlyIngestSegment] = queue.Queue(capacity)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._worker is not None:
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, name="market-data-durable-drain", daemon=True)
            self._worker.start()

    def submit(self, segment: OnlyIngestSegment) -> None:
        try:
            self._queue.put_nowait(segment)
        except queue.Full:
            # The sealed WAL remains authoritative and recover_all() will find it.
            # Explicit health/backlog exposes that normal drain is degraded.
            self._last_error = "MARKET_DATA_DRAIN_QUEUE_FULL"
            return

    def drain_pending(self) -> tuple[str, ...]:
        """Deterministic non-threaded drain boundary for tests and shutdown."""

        results: list[str] = []
        pending = self._queue.qsize()
        for _ in range(pending):
            try:
                segment = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                results.extend(self._recovery.recover_all())
                self._last_error = None
            except Exception as exc:
                # Sealed WAL remains discoverable by the same coordinator.
                self._last_error = f"{type(exc).__name__}:{exc}"
                self._queue.put_nowait(segment)
                break
            finally:
                self._queue.task_done()
        return tuple(results)

    def stop(self) -> None:
        self._stop.set()
        worker = self._worker
        if worker is not None:
            worker.join()
        self._worker = None

    def health(self) -> OnlyMarketDataHealth:
        base = self._recovery.health()
        return OnlyMarketDataHealth(
            OnlyRecordingState.DEGRADED if self._last_error is not None else base.recording_state,
            base.wal_bytes_used,
            base.wal_capacity,
            base.open_segments,
            base.sealed_uncommitted_segments,
            base.oldest_uncommitted_age,
            self._queue.qsize(),
            base.last_verified_segment,
            base.last_committed_segment,
            base.recovery_count,
            self._last_error or base.last_recovery_error,
            base.coverage_revision_lag,
            base.clickhouse_write_latency_seconds,
            base.postgres_commit_latency_seconds,
            base.postgres_commit_errors,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                segment = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._recovery.recover_all()
                self._last_error = None
            except Exception as exc:
                # Do not delete or acknowledge the sealed WAL. Recovery owns retry.
                self._last_error = f"{type(exc).__name__}:{exc}"
                try:
                    self._queue.put_nowait(segment)
                except queue.Full:
                    self._last_error = "MARKET_DATA_DRAIN_QUEUE_FULL"
                self._stop.wait(0.25)
            finally:
                self._queue.task_done()


__all__ = ["OnlyMarketDataDrainService"]
