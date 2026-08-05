import pytest

from onlyalpha.execution import OnlyExecutionRecoveryStatus, OnlyRuntimeProjectionComponent
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
def test_failure_before_each_real_target_recovers_exact_prefix_without_duplicate_authority(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    baseline = OnlyRealExecutionRecoveryHarness.create()
    assert baseline.recover().succeeded
    expected = baseline.manager_digest()

    harness = OnlyRealExecutionRecoveryHarness.create(target_fault=(component, "before"))
    failed = harness.recover()
    projection = next(item for item in harness.bundle.transaction.projections if item.identity.component is component)

    assert failed.status is OnlyExecutionRecoveryStatus.FAILED
    assert failed.failure_component is component
    assert not harness.bundle.transaction_store.ready_records(harness.bundle.transaction.runtime_id)
    assert harness.bundle.transaction_store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()
    assert len(harness.applied_ledger.records()) == projection.identity.projection_sequence - 1

    recovered = harness.recover()

    assert recovered.succeeded
    assert harness.manager_digest() == expected
    assert len(harness.applied_ledger.records()) == len(_COMPONENTS)
    assert harness.bundle.transaction_store.ready_count(harness.bundle.transaction.runtime_id) == 1


@pytest.mark.parametrize("component", _COMPONENTS, ids=lambda item: item.value)
def test_failure_after_real_target_return_recovers_as_idempotent_without_duplicate_authority(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    baseline = OnlyRealExecutionRecoveryHarness.create()
    assert baseline.recover().succeeded
    expected = baseline.manager_digest()

    harness = OnlyRealExecutionRecoveryHarness.create(target_fault=(component, "after"))
    failed = harness.recover()
    projection = next(item for item in harness.bundle.transaction.projections if item.identity.component is component)

    assert failed.status is OnlyExecutionRecoveryStatus.FAILED
    assert len(harness.applied_ledger.records()) == projection.identity.projection_sequence
    assert harness.bundle.transaction_store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()

    recovered = harness.recover()

    assert recovered.succeeded
    assert recovered.idempotent_transactions == 1
    assert harness.manager_digest() == expected
