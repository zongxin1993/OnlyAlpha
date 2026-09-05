"""Business-transaction Port for Research execution ownership."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from onlyalpha.research.run import OnlyResearchRun, OnlyResearchRunFailure

from .model import (
    OnlyResearchExecutionClaim,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchWorkerInstanceId,
)
from .policy import OnlyResearchRetryDecision
from .reconciliation import OnlyResearchSemanticCompletionInspection


class OnlyResearchExecutionStore(Protocol):
    def load_attempt(self, attempt_id: OnlyResearchRunAttemptId) -> OnlyResearchRunAttempt: ...

    def claim_next(
        self,
        *,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        attempt_id: OnlyResearchRunAttemptId,
        lease_duration: timedelta,
        max_attempts: int,
        run_started_at: datetime,
        eligible_run_ids: tuple[str, ...],
    ) -> OnlyResearchExecutionClaim | None: ...

    def heartbeat(
        self,
        *,
        attempt_id: OnlyResearchRunAttemptId,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        lease_duration: timedelta,
    ) -> OnlyResearchRunAttempt: ...

    def expire_next(
        self,
        *,
        max_attempts: int,
        run_finished_at: datetime,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyResearchRunAttempt | None: ...

    def load_cancellation_recovery_candidate(
        self,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyResearchRun | None: ...

    def reconcile_cancellation(
        self,
        *,
        expected: OnlyResearchRun,
        run_finished_at: datetime,
        inspection: OnlyResearchSemanticCompletionInspection,
    ) -> OnlyResearchRun: ...

    def complete(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
        research_result_fingerprint: str,
        artifact_content_fingerprint: str,
        calculation_execution_evidence_fingerprints: tuple[str, ...],
    ) -> OnlyResearchRun: ...

    def fail(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
        failure: OnlyResearchRunFailure,
        retry_decision: OnlyResearchRetryDecision,
    ) -> OnlyResearchRun: ...

    def cancel(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
    ) -> OnlyResearchRun: ...


__all__ = ["OnlyResearchExecutionStore"]
