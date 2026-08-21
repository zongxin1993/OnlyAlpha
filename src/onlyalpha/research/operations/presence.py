"""Worker-owned presence heartbeat; never an execution-ownership authority."""

from __future__ import annotations

import logging
from datetime import timedelta
from threading import Event, Thread

from onlyalpha.research.execution.model import OnlyResearchWorkerInstanceId

from .logging import only_log_research_operational_event
from .store import OnlyResearchWorkerPresenceWriter

_LOG = logging.getLogger(__name__)


class OnlyResearchWorkerPresenceReporter:
    def __init__(
        self,
        *,
        writer: OnlyResearchWorkerPresenceWriter,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        service_version: str,
        heartbeat_interval: timedelta = timedelta(seconds=15),
    ) -> None:
        if heartbeat_interval <= timedelta(0):
            raise ValueError("presence heartbeat_interval must be positive")
        self._writer = writer
        self._worker_instance_id = worker_instance_id
        self._service_version = service_version
        self._heartbeat_interval = heartbeat_interval
        self._stop = Event()
        self._thread = Thread(target=self._heartbeat_loop, name=f"research-presence-{worker_instance_id}")

    def start(self) -> None:
        self._writer.announce_worker(self._worker_instance_id, service_version=self._service_version)
        self._thread.start()

    def draining(self) -> None:
        try:
            self._writer.mark_worker_draining(self._worker_instance_id)
        except Exception:
            only_log_research_operational_event(
                _LOG,
                logging.ERROR,
                "research.worker.presence_failed",
                worker_instance_id=str(self._worker_instance_id),
                failure_code="WORKER_PRESENCE_UNAVAILABLE",
            )

    def stop(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=self._heartbeat_interval.total_seconds() + 1.0)
            if self._thread.is_alive():
                raise RuntimeError("Research Worker presence thread did not stop within its bounded deadline")

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_interval.total_seconds()):
            try:
                self._writer.heartbeat_worker(self._worker_instance_id)
            except Exception:
                only_log_research_operational_event(
                    _LOG,
                    logging.ERROR,
                    "research.worker.presence_failed",
                    worker_instance_id=str(self._worker_instance_id),
                    failure_code="WORKER_PRESENCE_UNAVAILABLE",
                )


__all__ = ["OnlyResearchWorkerPresenceReporter"]
