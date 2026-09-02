from datetime import UTC, datetime

import pytest

from onlyalpha.backtest import (
    OnlyBacktestProfileReference,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestSpecification,
)
from onlyalpha.backtest.errors import OnlyBacktestIntegrityError, OnlyBacktestStateConflictError


def _specification() -> OnlyBacktestSpecification:
    return OnlyBacktestSpecification(
        strategy_fingerprint="a" * 64,
        dataset_binding_fingerprint="b" * 64,
        market_product_configuration_fingerprint="c" * 64,
        portfolio_profile=OnlyBacktestProfileReference("fixed-capital", "1"),
        risk_profile=OnlyBacktestProfileReference("default-risk", "1"),
        execution_profile=OnlyBacktestProfileReference("virtual-next-bar", "1"),
        base_currency="USDT",
        initial_capital="100000",
    )


def test_backtest_specification_round_trip_and_identity_are_canonical() -> None:
    expected = _specification()
    restored = OnlyBacktestSpecification.from_dict(expected.to_dict())

    assert restored == expected
    assert restored.specification_fingerprint == expected.specification_fingerprint
    assert "worker" not in restored.to_dict()
    assert "path" not in restored.to_dict()


def test_backtest_specification_rejects_unknown_product_fields() -> None:
    payload = _specification().to_dict()
    payload["engine_config"] = "forbidden"

    with pytest.raises(ValueError, match="fields are invalid"):
        OnlyBacktestSpecification.from_dict(payload)


def test_backtest_run_requires_verified_evidence_before_completion() -> None:
    queued_at = datetime(2026, 9, 2, tzinfo=UTC)
    queued = OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        specification=_specification(),
        admission_resolution_fingerprint="d" * 64,
        queued_at=queued_at,
    )
    running = queued.transition(OnlyBacktestRunState.RUNNING, at=queued_at)

    with pytest.raises(OnlyBacktestIntegrityError, match="verified Evidence"):
        running.transition(OnlyBacktestRunState.COMPLETED, at=queued_at)

    completed = running.transition(
        OnlyBacktestRunState.COMPLETED,
        at=queued_at,
        evidence_fingerprint="e" * 64,
        result_fingerprint="f" * 64,
        determinism_fingerprint="1" * 64,
    )
    assert completed.state is OnlyBacktestRunState.COMPLETED

    with pytest.raises(OnlyBacktestStateConflictError):
        completed.transition(OnlyBacktestRunState.RUNNING, at=queued_at)
