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


def test_finite_limit_policy_is_explicit_bounded_input_not_an_implicit_strategy_change() -> None:
    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy

    policy = OnlyBacktestLimitPolicy("4", "10.00", "12.00", "2", 2)
    assert OnlyBacktestLimitPolicy.from_dict(policy.to_dict()) == policy
    assert policy.to_dict() == {
        "schema_version": 1,
        "kind": "FINITE_LONG_LIMIT",
        "quantity": "4",
        "entry_limit": "10.00",
        "exit_limit": "12.00",
        "maximum_fill_quantity": "2",
        "round_trips": 2,
    }
    for quantity, maximum, rounds in (("1E+1000000000", "1", 1), ("0", "1", 1), ("100", "1", 8), ("1", "1", True)):
        with pytest.raises(ValueError, match="BACKTEST_LIMIT_POLICY"):
            OnlyBacktestLimitPolicy(quantity, "10.00", "12.00", maximum, rounds)


def test_native_specification_pins_limit_policy_and_preserves_historical_specification_bytes() -> None:
    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy

    historical = _specification()
    original = historical.to_dict()
    policy = OnlyBacktestLimitPolicy("4", "10.00", "12.00", "2", 1)
    native = replace(historical, schema_version=2, order_policy=policy)
    assert OnlyBacktestSpecification.from_dict(native.to_dict()) == native
    assert native.to_dict()["runtime_options"]["order_policy"] == policy.to_dict()
    assert native.specification_fingerprint != historical.specification_fingerprint
    assert (
        replace(native, order_policy=replace(policy, quantity="3")).specification_fingerprint
        != native.specification_fingerprint
    )
    assert OnlyBacktestSpecification.from_dict(original).to_dict() == original
    for version, value in ((1, policy), (2, None)):
        with pytest.raises(ValueError, match="BACKTEST_SPECIFICATION"):
            replace(historical, schema_version=version, order_policy=value)


def test_native_capital_rejects_unbounded_text_before_decimal_expansion(monkeypatch) -> None:
    import onlyalpha.backtest.model as model
    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy

    original = _specification()
    policy = OnlyBacktestLimitPolicy("1", "1", "1", "1", 1)

    def forbidden(_):
        pytest.fail("unsupported native numeric text reached Decimal expansion")

    monkeypatch.setattr(model, "Decimal", forbidden)
    with pytest.raises(ValueError, match="BACKTEST_INITIAL_CAPITAL_INVALID"):
        replace(original, schema_version=2, order_policy=policy, initial_capital="1e99999999")
