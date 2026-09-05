"""Finite deterministic Scheduler operations over the execution Store Port."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority

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
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        process_generation_fingerprint: str,
        attempt_id_factory: Callable[[], OnlyResearchRunAttemptId] = OnlyResearchRunAttemptId.new,
    ) -> None:
        self._store = store
        self._policy = policy
        self._now_utc = now_utc
        self._attempt_id_factory = attempt_id_factory
        self._runtime_generations = runtime_generations
        self._process_generation_fingerprint = process_generation_fingerprint

    def claim_once(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchExecutionClaim | None:
        eligible = self._runtime_generations.work_ids_for_generation(self._process_generation_fingerprint)
        if not eligible:
            return None
        return self._store.claim_next(
            worker_instance_id=worker_instance_id,
            attempt_id=self._attempt_id_factory(),
            lease_duration=self._policy.lease_duration,
            max_attempts=self._policy.max_attempts,
            run_started_at=self._now_utc(),
            eligible_run_ids=eligible,
        )

    def expire_once(self) -> OnlyResearchRunAttempt | None:
        eligible = self._runtime_generations.work_ids_for_generation(self._process_generation_fingerprint)
        return self._store.expire_next(
            max_attempts=self._policy.max_attempts,
            run_finished_at=self._now_utc(),
            eligible_run_ids=eligible,
        )


__all__ = ["OnlyResearchScheduler"]
