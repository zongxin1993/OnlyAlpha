from datetime import UTC, datetime

import pytest

from onlyalpha.backtest import (
    OnlyBacktestAttemptId,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestRun,
    OnlyBacktestRunId,
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
        admission_resolution_fingerprint="d" * 64,
        queued_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_attempt_claim_and_fencing() -> None:
    store = OnlyInMemoryBacktestExecutionStore((_run(),))
    claim = store.claim_next(
        OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), OnlyBacktestExecutionPolicy()
    )
    assert claim is not None
    assert (
        store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), OnlyBacktestExecutionPolicy())
        is None
    )
    store.heartbeat(claim, OnlyBacktestExecutionPolicy().lease_duration)

    with pytest.raises(RuntimeError, match="FENCED"):
        store.heartbeat(claim, OnlyBacktestExecutionPolicy().lease_duration)
