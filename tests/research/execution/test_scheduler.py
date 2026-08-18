from __future__ import annotations

from datetime import UTC, datetime, timedelta

from onlyalpha.research.execution import (
    OnlyResearchExecutionPolicy,
    OnlyResearchRunAttemptId,
    OnlyResearchScheduler,
    OnlyResearchWorkerInstanceId,
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)


class _Store:
    def __init__(self) -> None:
        self.claim_args: dict[str, object] = {}
        self.expire_args: dict[str, object] = {}

    def claim_next(self, **kwargs: object) -> None:
        self.claim_args = kwargs
        return None

    def expire_next(self, **kwargs: object) -> None:
        self.expire_args = kwargs
        return None


def test_scheduler_finite_operations_supply_policy_identity_and_application_clock() -> None:
    store = _Store()
    attempt_id = OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000111")
    worker_id = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000112")
    policy = OnlyResearchExecutionPolicy(
        lease_duration=timedelta(seconds=10), heartbeat_interval=timedelta(seconds=2), max_attempts=4
    )
    scheduler = OnlyResearchScheduler(
        store=store,  # type: ignore[arg-type]
        policy=policy,
        now_utc=lambda: NOW,
        attempt_id_factory=lambda: attempt_id,
    )
    assert scheduler.claim_once(worker_id) is None
    assert store.claim_args == {
        "worker_instance_id": worker_id,
        "attempt_id": attempt_id,
        "lease_duration": timedelta(seconds=10),
        "max_attempts": 4,
        "run_started_at": NOW,
    }
    assert scheduler.expire_once() is None
    assert store.expire_args == {"max_attempts": 4, "run_finished_at": NOW}
