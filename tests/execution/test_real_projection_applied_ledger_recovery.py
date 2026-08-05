import pytest

from onlyalpha.execution import (
    OnlyExecutionRecoveryStatus,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionComponent,
)
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness

_COMPONENTS = tuple(
    component
    for component in OnlyRuntimeProjectionComponent
    if component
    not in {
        OnlyRuntimeProjectionComponent.MARGIN,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
    }
)


@pytest.mark.parametrize("component", _COMPONENTS, ids=lambda item: item.value)
def test_manager_install_before_applied_ledger_failure_repairs_index_without_reapplying_economics(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    baseline = OnlyRealExecutionRecoveryHarness.create()
    assert baseline.recover().succeeded
    expected = baseline.manager_digest()

    harness = OnlyRealExecutionRecoveryHarness.create(ledger_fault=component)
    failed = harness.recover()
    projection = next(item for item in harness.bundle.transaction.projections if item.identity.component is component)

    assert failed.status is OnlyExecutionRecoveryStatus.FAILED
    assert len(harness.applied_ledger.records()) == projection.identity.projection_sequence - 1
    assert harness.bundle.transaction_store.ready_count(harness.bundle.transaction.runtime_id) == 0

    recovered = harness.recover()

    assert recovered.succeeded
    assert recovered.recovered_transactions == 1
    assert harness.manager_digest() == expected
    assert len(harness.applied_ledger.records()) == len(_COMPONENTS)


def test_lost_applied_ledger_is_rebuilt_from_all_real_manager_result_authority() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    assert harness.recover().succeeded
    manager_before = harness.manager_digest()
    harness.rebuild_with_clean_ledger()

    recovered = OnlyRuntimeProjectionApplier(harness.targets).apply(harness.bundle.transaction)

    assert tuple(item.status for item in recovered.recovered) == (OnlyProjectionApplyStatus.RECOVERED,) * len(
        _COMPONENTS
    )
    assert harness.manager_digest() == manager_before
    assert len(harness.applied_ledger.records()) == len(_COMPONENTS)
