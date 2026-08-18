"""Finite deterministic Scheduler operations over the execution Store Port."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .model import (
    OnlyResearchExecutionClaim,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchWorkerInstanceId,
)
from .policy import OnlyResearchExecutionPolicy
from .store import OnlyResearchExecutionStore


class OnlyResearchScheduler:
    def __init__(
        self,
        *,
        store: OnlyResearchExecutionStore,
        policy: OnlyResearchExecutionPolicy,
        now_utc: Callable[[], datetime],
        attempt_id_factory: Callable[[], OnlyResearchRunAttemptId] = OnlyResearchRunAttemptId.new,
    ) -> None:
        self._store = store
        self._policy = policy
        self._now_utc = now_utc
        self._attempt_id_factory = attempt_id_factory

    def claim_once(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchExecutionClaim | None:
        return self._store.claim_next(
            worker_instance_id=worker_instance_id,
            attempt_id=self._attempt_id_factory(),
            lease_duration=self._policy.lease_duration,
            max_attempts=self._policy.max_attempts,
            run_started_at=self._now_utc(),
        )

    def expire_once(self) -> OnlyResearchRunAttempt | None:
        return self._store.expire_next(
            max_attempts=self._policy.max_attempts,
            run_finished_at=self._now_utc(),
        )


__all__ = ["OnlyResearchScheduler"]
