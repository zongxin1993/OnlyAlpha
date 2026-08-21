"""Mechanical, read-only diagnoses derived from durable operational facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from onlyalpha.research.execution.model import OnlyResearchRunAttemptState
from onlyalpha.research.run import OnlyResearchRunState

from .model import (
    OnlyResearchOperationalDiagnosisCode,
    OnlyResearchOperationalSnapshot,
    OnlyResearchRunDiagnosis,
    OnlyResearchRunOperationalRecord,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchDiagnosticPolicy:
    queue_age_threshold: timedelta = timedelta(minutes=5)
    worker_stale_after: timedelta = timedelta(seconds=45)

    def __post_init__(self) -> None:
        if self.queue_age_threshold <= timedelta(0) or self.worker_stale_after <= timedelta(0):
            raise ValueError("diagnostic thresholds must be positive")


class OnlyResearchOperationalDiagnosticService:
    """Observe facts only; this service has no mutation port."""

    def __init__(self, policy: OnlyResearchDiagnosticPolicy | None = None) -> None:
        self._policy = policy or OnlyResearchDiagnosticPolicy()

    def diagnose(self, snapshot: OnlyResearchOperationalSnapshot) -> tuple[OnlyResearchRunDiagnosis, ...]:
        fresh_worker = any(
            worker.fresh_at(snapshot.observed_at, self._policy.worker_stale_after) for worker in snapshot.workers
        )
        return tuple(self._diagnose(record, snapshot, fresh_worker) for record in snapshot.runs)

    def _diagnose(
        self,
        record: OnlyResearchRunOperationalRecord,
        snapshot: OnlyResearchOperationalSnapshot,
        fresh_worker: bool,
    ) -> OnlyResearchRunDiagnosis:
        run = record.run
        active = tuple(item for item in record.attempts if item.state is OnlyResearchRunAttemptState.ACTIVE)
        code = OnlyResearchOperationalDiagnosisCode.HEALTHY
        if run.state is OnlyResearchRunState.CANCEL_REQUESTED and not active:
            code = OnlyResearchOperationalDiagnosisCode.CANCELLATION_RECOVERY_PENDING
        elif any(item.lease_expires_at <= snapshot.observed_at for item in active):
            code = OnlyResearchOperationalDiagnosisCode.ACTIVE_LEASE_OVERDUE
        elif run.state is OnlyResearchRunState.RUNNING and not active:
            code = OnlyResearchOperationalDiagnosisCode.RUNNING_WITHOUT_ACTIVE_ATTEMPT
        elif run.state is OnlyResearchRunState.QUEUED and not fresh_worker:
            code = OnlyResearchOperationalDiagnosisCode.NO_READY_WORKER
        elif (
            run.state is OnlyResearchRunState.QUEUED
            and snapshot.observed_at - run.queued_at > self._policy.queue_age_threshold
        ):
            code = OnlyResearchOperationalDiagnosisCode.QUEUE_AGED
        return OnlyResearchRunDiagnosis(record, code, snapshot.observed_at)


__all__ = [name for name in globals() if name.startswith("Only")]
