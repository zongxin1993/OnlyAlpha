import pytest

from onlyalpha.execution import OnlyExecutionProjectionComponent, OnlyExecutionRecoveryStatus
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


@pytest.mark.parametrize(
    "component",
    (
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.POSITION_RESERVATION,
        OnlyExecutionProjectionComponent.VALUATION,
    ),
)
def test_long_close_mid_projection_failure_resumes_without_double_accounting(
    component: OnlyExecutionProjectionComponent,
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
