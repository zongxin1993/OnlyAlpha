"""Backtest Worker operational presence; never execution ownership authority."""

from __future__ import annotations

import logging
from datetime import timedelta
from threading import Event, Thread
from typing import Protocol

from .execution import OnlyBacktestWorkerInstanceId

_LOG = logging.getLogger(__name__)


class OnlyBacktestWorkerPresenceWriter(Protocol):
    def announce_worker(self, worker_id: OnlyBacktestWorkerInstanceId, service_version: str) -> None: ...

    def heartbeat_worker(self, worker_id: OnlyBacktestWorkerInstanceId) -> None: ...

    def mark_worker_draining(self, worker_id: OnlyBacktestWorkerInstanceId) -> None: ...


class OnlyBacktestWorkerPresenceReporter:
    def __init__(
        self,
        writer: OnlyBacktestWorkerPresenceWriter,
        worker_id: OnlyBacktestWorkerInstanceId,
        service_version: str,
        heartbeat_interval: timedelta = timedelta(seconds=15),
    ) -> None:
        if heartbeat_interval <= timedelta(0) or not service_version.strip():
            raise ValueError("BACKTEST_WORKER_PRESENCE_CONFIGURATION_INVALID")
        self._writer = writer
        self._worker_id = worker_id
        self._service_version = service_version
        self._heartbeat_interval = heartbeat_interval
        self._stop = Event()
        self._thread = Thread(target=self._heartbeat, name=f"backtest-presence-{worker_id.value}", daemon=False)

    def start(self) -> None:
        self._writer.announce_worker(self._worker_id, self._service_version)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=self._heartbeat_interval.total_seconds() + 1)
            if self._thread.is_alive():
                raise RuntimeError("BACKTEST_WORKER_PRESENCE_STOP_TIMEOUT")

    def draining(self) -> None:
        self._writer.mark_worker_draining(self._worker_id)

    def _heartbeat(self) -> None:
        while not self._stop.wait(self._heartbeat_interval.total_seconds()):
            try:
                self._writer.heartbeat_worker(self._worker_id)
            except Exception:
                _LOG.exception("BACKTEST_WORKER_PRESENCE_UNAVAILABLE")


__all__ = [name for name in globals() if name.startswith("Only")]
