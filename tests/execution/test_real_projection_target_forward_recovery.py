import pytest

from onlyalpha.execution import (
    OnlyProjectionApplyResult,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionBatchStatus,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionTarget,
)
from onlyalpha.transaction.applied_projection import OnlyRuntimeProjectionApplyContext
from tests.execution.targets.support import only_test_projection_target_bundle
from tests.execution.test_real_projection_target_manager_parity import _projection_authority


class _OnlyTestFailOnceTarget:
    def __init__(self, delegate: OnlyRuntimeProjectionTarget) -> None:
        self._delegate = delegate
        self._failed = False

    @property
    def component(self) -> OnlyRuntimeProjectionComponent:
        return self._delegate.component

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected target failure")
        return self._delegate.apply_execution_projection(context)


@pytest.mark.parametrize(
    "failed_component",
    tuple(
        component
        for component in OnlyRuntimeProjectionComponent
        if component
        not in {
            OnlyRuntimeProjectionComponent.MARGIN,
            OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
            OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
            OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
            OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
            OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
            OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
            OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE,
        }
    ),
)
def test_forward_recovery_resumes_from_applied_projection_ledger(
    failed_component: OnlyRuntimeProjectionComponent,
) -> None:
    control = only_test_projection_target_bundle()
    assert control.apply_all().status is OnlyRuntimeProjectionBatchStatus.COMPLETED

    recovered = only_test_projection_target_bundle()
    targets = dict(recovered.targets)
    targets[failed_component] = _OnlyTestFailOnceTarget(targets[failed_component])
    applier = OnlyRuntimeProjectionApplier(targets)
    first = applier.apply(recovered.transaction)
    assert first.status is OnlyRuntimeProjectionBatchStatus.FAILED
    assert first.failed_projection is not None
    assert first.failed_projection.identity.component is failed_component
    projection_sequence = first.failed_projection.identity.projection_sequence
    assert len(recovered.applied_ledger.records()) == projection_sequence - 1

    resumed = applier.apply(recovered.transaction)
    assert resumed.status is OnlyRuntimeProjectionBatchStatus.COMPLETED
    assert len(resumed.idempotent) == projection_sequence - 1
    assert len(resumed.applied) == 14 - projection_sequence
    assert len(recovered.applied_ledger.records()) == 13
    assert _projection_authority(recovered.environment) == _projection_authority(control.environment)
