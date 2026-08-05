import pytest

from onlyalpha.execution import (
    OnlyFeeExecutionProjection,
    OnlyRuntimeProjectionComponent,
    OnlySettlementExecutionProjection,
    only_execution_state_hash,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


@pytest.mark.parametrize(
    "component,manager_name",
    (
        (OnlyRuntimeProjectionComponent.POSITION, "position_manager"),
        (OnlyRuntimeProjectionComponent.ALLOCATION, "allocation_manager"),
        (OnlyRuntimeProjectionComponent.ACCOUNT, "account_manager"),
        (OnlyRuntimeProjectionComponent.STRATEGY_LEDGER, "strategy_ledger_manager"),
    ),
)
def test_repository_failure_leaves_manager_and_applied_ledger_unchanged(
    component: OnlyRuntimeProjectionComponent,
    manager_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = only_test_projection_target_bundle()
    manager = getattr(bundle.environment.runtime, manager_name)

    def fail(_snapshot: object) -> None:
        raise RuntimeError("injected repository replace failure")

    monkeypatch.setattr(manager._repository, "replace_execution_authority", fail)
    before = only_test_runtime_authority_digest(bundle.environment)
    with pytest.raises(RuntimeError, match="injected repository replace failure"):
        bundle.targets[component].apply_execution_projection(only_test_projection_context(bundle, component))
    assert only_test_runtime_authority_digest(bundle.environment) == before
    assert not bundle.applied_ledger.records()


def test_fee_restore_validation_failure_is_atomic() -> None:
    bundle = only_test_projection_target_bundle()
    component = OnlyRuntimeProjectionComponent.FEE
    context = only_test_projection_context(bundle, component)
    projection = context.projection
    assert isinstance(projection, OnlyFeeExecutionProjection)
    object.__setattr__(projection.after, "record_sequence_head", -1)
    object.__setattr__(projection.identity, "result_state_hash", only_execution_state_hash(projection.after))
    before = only_test_runtime_authority_digest(bundle.environment)
    with pytest.raises(ValueError, match="sequence head"):
        bundle.targets[component].apply_execution_projection(context)
    assert only_test_runtime_authority_digest(bundle.environment) == before
    assert not bundle.applied_ledger.records()


def test_settlement_restore_validation_failure_is_atomic() -> None:
    bundle = only_test_projection_target_bundle()
    component = OnlyRuntimeProjectionComponent.SETTLEMENT
    context = only_test_projection_context(bundle, component)
    projection = context.projection
    assert isinstance(projection, OnlySettlementExecutionProjection)
    object.__setattr__(projection.after, "record_sequence_head", -1)
    object.__setattr__(projection.identity, "result_state_hash", only_execution_state_hash(projection.after))
    before = only_test_runtime_authority_digest(bundle.environment)
    with pytest.raises(ValueError, match="record sequence"):
        bundle.targets[component].apply_execution_projection(context)
    assert only_test_runtime_authority_digest(bundle.environment) == before
    assert not bundle.applied_ledger.records()
