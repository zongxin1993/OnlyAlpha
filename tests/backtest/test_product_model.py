from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestExecutionSemanticBinding,
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


def _resolution() -> OnlyBacktestAdmissionResolution:
    return OnlyBacktestAdmissionResolution(
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
    )


def test_backtest_specification_round_trip_and_identity_are_canonical() -> None:
    expected = _specification()
    restored = OnlyBacktestSpecification.from_dict(expected.to_dict())

    assert restored == expected
    assert restored.specification_fingerprint == expected.specification_fingerprint
    assert "worker" not in restored.to_dict()
    assert "path" not in restored.to_dict()


def test_admission_resolution_round_trip_and_identity_are_canonical() -> None:
    expected = _resolution()
    restored = OnlyBacktestAdmissionResolution.from_dict(expected.to_dict())

    assert restored == expected
    assert restored.admission_resolution_fingerprint == expected.admission_resolution_fingerprint


def test_execution_semantic_binding_excludes_operational_identity() -> None:
    first = OnlyBacktestExecutionSemanticBinding.from_admission(_specification(), _resolution())
    second = OnlyBacktestExecutionSemanticBinding.from_admission(_specification(), _resolution())

    assert first == second
    assert first.fingerprint == second.fingerprint
    assert not ({"run_id", "attempt_id", "worker_instance_id", "config_path"} & set(first.to_dict()))

    changed = OnlyBacktestExecutionSemanticBinding.from_admission(
        _specification(),
        replace(_resolution(), kernel_semantics_version="kernel-v2"),
    )
    assert changed.fingerprint != first.fingerprint


def test_execution_semantic_binding_rejects_cross_authority_drift() -> None:
    with pytest.raises(ValueError, match="BACKTEST_EXECUTION_SEMANTIC_BINDING_INVALID"):
        OnlyBacktestExecutionSemanticBinding.from_admission(
            _specification(),
            replace(_resolution(), dataset_binding_fingerprint="f" * 64),
        )


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
        admission_resolution=_resolution(),
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
