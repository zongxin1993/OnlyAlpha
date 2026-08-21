"""Read-only Research operational diagnostics and minimal Worker presence facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from onlyalpha.research.execution.model import OnlyResearchRunAttempt, OnlyResearchWorkerInstanceId
from onlyalpha.research.run import OnlyResearchRun


class OnlyResearchOperationalDiagnosisCode(StrEnum):
    HEALTHY = "HEALTHY"
    QUEUE_AGED = "QUEUE_AGED"
    NO_READY_WORKER = "NO_READY_WORKER"
    RUNNING_WITHOUT_ACTIVE_ATTEMPT = "RUNNING_WITHOUT_ACTIVE_ATTEMPT"
    ACTIVE_LEASE_OVERDUE = "ACTIVE_LEASE_OVERDUE"
    CANCELLATION_RECOVERY_PENDING = "CANCELLATION_RECOVERY_PENDING"


@dataclass(frozen=True, slots=True)
class OnlyResearchWorkerPresence:
    worker_instance_id: OnlyResearchWorkerInstanceId
    started_at: datetime
    last_seen_at: datetime
    service_version: str
    draining_since: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("started_at", "last_seen_at", "draining_since"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)):
                raise ValueError(f"{name} must be timezone-aware UTC")
        if self.last_seen_at < self.started_at:
            raise ValueError("last_seen_at precedes started_at")
        if self.draining_since is not None and self.draining_since < self.started_at:
            raise ValueError("draining_since precedes started_at")
        if not self.service_version:
            raise ValueError("service_version is required")

    def fresh_at(self, observed_at: datetime, stale_after: timedelta) -> bool:
        return self.draining_since is None and self.last_seen_at > observed_at - stale_after


@dataclass(frozen=True, slots=True)
class OnlyResearchRunOperationalRecord:
    run: OnlyResearchRun
    attempts: tuple[OnlyResearchRunAttempt, ...]

    def __post_init__(self) -> None:
        expected = tuple(sorted(self.attempts, key=lambda item: (item.attempt_number, item.attempt_id.value)))
        if self.attempts != expected or any(item.run_id != self.run.run_id for item in self.attempts):
            raise ValueError("Attempt history must be linked and deterministically ordered")


@dataclass(frozen=True, slots=True)
class OnlyResearchOperationalSnapshot:
    observed_at: datetime
    workers: tuple[OnlyResearchWorkerPresence, ...]
    runs: tuple[OnlyResearchRunOperationalRecord, ...]

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(self.observed_at):
            raise ValueError("observed_at must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class OnlyResearchRunDiagnosis:
    record: OnlyResearchRunOperationalRecord
    code: OnlyResearchOperationalDiagnosisCode
    observed_at: datetime


__all__ = [name for name in globals() if name.startswith("Only")]
