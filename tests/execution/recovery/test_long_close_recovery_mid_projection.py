import pytest

from onlyalpha.execution import OnlyExecutionRecoveryStatus, OnlyRuntimeProjectionComponent
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


@pytest.mark.parametrize(
    "component",
    (
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.VALUATION,
    ),
)
def test_long_close_mid_projection_failure_resumes_without_double_accounting(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    control = OnlyRealExecutionRecoveryHarness.create(long_close=True)
    assert control.recover().succeeded

    recovered = OnlyRealExecutionRecoveryHarness.create(
        long_close=True,
        target_fault=(component, "before"),
    )
    first = recovered.recover()
    assert first.status is OnlyExecutionRecoveryStatus.FAILED

    second = recovered.recover()

    assert second.succeeded
    assert recovered.manager_digest() == control.manager_digest()
    assert len(recovered.applied_ledger.records()) == len(recovered.bundle.transaction.projections)
