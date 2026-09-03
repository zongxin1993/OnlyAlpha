from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestAttemptId,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestRun,
    OnlyBacktestRunFailure,
    OnlyBacktestRunFailurePhase,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestSpecification,
    OnlyBacktestWorkerInstanceId,
    OnlyInMemoryBacktestExecutionStore,
)
from onlyalpha.backtest.model import OnlyBacktestProfileReference


def _run() -> OnlyBacktestRun:
    spec = OnlyBacktestSpecification(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        OnlyBacktestProfileReference("portfolio", "1"),
        OnlyBacktestProfileReference("risk", "1"),
        OnlyBacktestProfileReference("execution", "1"),
        "USDT",
        "10",
    )
    return OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        specification=spec,
        admission_resolution=OnlyBacktestAdmissionResolution(
            1,
            "a" * 64,
            "b" * 64,
            "d" * 64,
            "e" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "kernel-v1",
            (),
        ),
        queued_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_attempt_claim_and_fencing() -> None:
    current = [datetime(2026, 9, 2, tzinfo=UTC)]
    store = OnlyInMemoryBacktestExecutionStore((_run(),), now_utc=lambda: current[0])
    policy = OnlyBacktestExecutionPolicy()
    claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert claim is not None
    assert store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy) is None
    store.heartbeat(claim, policy.lease_duration)
    current[0] += policy.lease_duration + timedelta(microseconds=1)
    assert store.expire_next(policy) is not None
    replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert replacement is not None
    assert replacement.run.run_id == claim.run.run_id
    assert replacement.attempt.fencing_token > claim.attempt.fencing_token

    with pytest.raises(RuntimeError, match="FENCED"):
        store.heartbeat(claim, policy.lease_duration)


def test_default_policy_retries_actual_backtest_store_unavailable_code() -> None:
    store = OnlyInMemoryBacktestExecutionStore(
        (_run(),),
        now_utc=lambda: datetime(2026, 9, 2, tzinfo=UTC),
    )
    policy = OnlyBacktestExecutionPolicy()
    first = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert first is not None

    retained = store.fail(
        first,
        OnlyBacktestRunFailure(
            OnlyBacktestRunFailurePhase.OPERATIONAL,
            "BACKTEST_STORE_UNAVAILABLE",
            "temporary database failure",
        ),
        policy,
    )

    assert retained.state is OnlyBacktestRunState.RUNNING
    replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert replacement is not None
    assert replacement.run.run_id == first.run.run_id
    assert replacement.attempt.attempt_number == 2
