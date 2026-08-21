"""Ports for Worker presence writes and read-only operational inspection."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.research.execution.model import OnlyResearchWorkerInstanceId
from onlyalpha.research.run import OnlyResearchRunId

from .model import OnlyResearchOperationalSnapshot, OnlyResearchWorkerPresence


class OnlyResearchWorkerPresenceWriter(Protocol):
    def announce_worker(
        self, worker_instance_id: OnlyResearchWorkerInstanceId, *, service_version: str
    ) -> OnlyResearchWorkerPresence: ...

    def heartbeat_worker(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchWorkerPresence: ...

    def mark_worker_draining(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchWorkerPresence: ...


class OnlyResearchOperationalReader(Protocol):
    def load_operational_snapshot(
        self, *, run_id: OnlyResearchRunId | None = None, limit: int = 100
    ) -> OnlyResearchOperationalSnapshot: ...


__all__ = [name for name in globals() if name.startswith("Only")]
