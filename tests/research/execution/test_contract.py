from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.research.execution import (
    OnlyResearchExecutionClaim,
    OnlyResearchExecutionPolicy,
    OnlyResearchRetryDecision,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.run import OnlyResearchRunFailure, OnlyResearchRunFailurePhase, OnlyResearchRunId

NOW = datetime(2026, 8, 18, tzinfo=UTC)
ATTEMPT_ID = OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000101")
RUN_ID = OnlyResearchRunId("00000000-0000-4000-8000-000000000102")
WORKER_ID = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000103")


def _active() -> OnlyResearchRunAttempt:
    return OnlyResearchRunAttempt(
        ATTEMPT_ID,
        RUN_ID,
        1,
        OnlyResearchRunAttemptState.ACTIVE,
        WORKER_ID,
        NOW,
        NOW,
        NOW + timedelta(minutes=2),
    )


def test_attempt_and_worker_identities_are_independent_canonical_uuid4() -> None:
    assert str(ATTEMPT_ID) != str(RUN_ID)
    assert isinstance(OnlyResearchRunAttemptId.new(), OnlyResearchRunAttemptId)
    assert isinstance(OnlyResearchWorkerInstanceId.new(), OnlyResearchWorkerInstanceId)
    with pytest.raises(ValueError, match="UUID4"):
        OnlyResearchRunAttemptId("00000000-0000-1000-8000-000000000101")
    with pytest.raises(ValueError, match="canonical UUID"):
        OnlyResearchWorkerInstanceId("invalid")


def test_attempt_state_facts_and_time_order_fail_closed() -> None:
    active = _active()
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.OPERATIONAL, "LEASE_EXPIRED", "expired")
    expired = replace(
        active,
        state=OnlyResearchRunAttemptState.EXPIRED,
        finished_at=NOW + timedelta(minutes=3),
        failure=failure,
    )
    assert expired.state.terminal and not active.state.terminal
    assert OnlyResearchExecutionClaim(active).attempt == active
    for changes in (
        {"attempt_number": 0},
        {"last_heartbeat_at": NOW - timedelta(seconds=1)},
        {"lease_expires_at": NOW - timedelta(seconds=1)},
        {"state": OnlyResearchRunAttemptState.FAILED, "finished_at": NOW + timedelta(seconds=1)},
        {
            "state": OnlyResearchRunAttemptState.SUCCEEDED,
            "finished_at": NOW + timedelta(seconds=1),
            "failure": failure,
        },
    ):
        with pytest.raises(ValueError):
            replace(active, **changes)
    with pytest.raises(ValueError, match="ACTIVE"):
        OnlyResearchExecutionClaim(expired)
    succeeded = replace(
        active,
        state=OnlyResearchRunAttemptState.SUCCEEDED,
        finished_at=NOW + timedelta(seconds=1),
    )
    assert succeeded.state.terminal
    for changes in (
        {"attempt_id": "bad"},
        {"run_id": "bad"},
        {"attempt_number": True},
        {"state": "ACTIVE"},
        {"worker_instance_id": "bad"},
        {"claimed_at": NOW.replace(tzinfo=None)},
        {
            "finished_at": NOW - timedelta(seconds=1),
            "state": OnlyResearchRunAttemptState.SUCCEEDED,
        },
    ):
        with pytest.raises(ValueError):
            replace(active, **changes)


def test_execution_policy_is_bounded_and_failure_classification_is_independent() -> None:
    policy = OnlyResearchExecutionPolicy(
        lease_duration=timedelta(seconds=20),
        heartbeat_interval=timedelta(seconds=5),
        max_attempts=2,
        retryable_failure_codes=frozenset({"TEMPORARY"}),
    )
    temporary = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.OPERATIONAL, "TEMPORARY", "retry")
    permanent = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.ADMISSION, "SEMANTIC_DRIFT", "stop")
    assert policy.retry_decision(temporary, attempt_number=1) is OnlyResearchRetryDecision.RETRY
    assert policy.retry_decision(temporary, attempt_number=2) is OnlyResearchRetryDecision.FINAL_FAIL
    assert policy.retry_decision(permanent, attempt_number=1) is OnlyResearchRetryDecision.FINAL_FAIL
    with pytest.raises(ValueError, match="shorter"):
        OnlyResearchExecutionPolicy(lease_duration=timedelta(seconds=5), heartbeat_interval=timedelta(seconds=5))
    with pytest.raises(ValueError, match="positive"):
        OnlyResearchExecutionPolicy(heartbeat_interval=timedelta(0))
    with pytest.raises(ValueError, match="positive integer"):
        OnlyResearchExecutionPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="upper-case"):
        OnlyResearchExecutionPolicy(retryable_failure_codes=frozenset({"temporary"}))
