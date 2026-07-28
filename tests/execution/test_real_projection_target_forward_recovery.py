import pytest

from onlyalpha.execution import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyProjectionApplyResult,
)
from onlyalpha.execution.applied_projection import OnlyExecutionProjectionApplyContext
from tests.execution.targets.support import only_test_projection_target_bundle
from tests.execution.test_real_projection_target_manager_parity import _projection_authority


class _OnlyTestFailOnceTarget:
    def __init__(self, delegate: OnlyExecutionProjectionTarget) -> None:
        self._delegate = delegate
        self._failed = False

    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        return self._delegate.component

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected target failure")
        return self._delegate.apply_execution_projection(context)


@pytest.mark.parametrize(
    "failed_component",
    tuple(
        component
        for component in OnlyExecutionProjectionComponent
        if component
        not in {
            OnlyExecutionProjectionComponent.MARGIN,
            OnlyExecutionProjectionComponent.POSITION_RESERVATION,
            OnlyExecutionProjectionComponent.MARGIN_RESERVATION,
        }
    ),
)
def test_forward_recovery_resumes_from_applied_projection_ledger(
    failed_component: OnlyExecutionProjectionComponent,
) -> None:
    control = only_test_projection_target_bundle()
    assert control.apply_all().status is OnlyExecutionProjectionBatchStatus.COMPLETED

    recovered = only_test_projection_target_bundle()
    targets = dict(recovered.targets)
    targets[failed_component] = _OnlyTestFailOnceTarget(targets[failed_component])
    applier = OnlyExecutionProjectionApplier(targets)
    first = applier.apply(recovered.transaction)
    assert first.status is OnlyExecutionProjectionBatchStatus.FAILED
    assert first.failed_projection is not None
    assert first.failed_projection.identity.component is failed_component
    projection_sequence = first.failed_projection.identity.projection_sequence
    assert len(recovered.applied_ledger.records()) == projection_sequence - 1

    resumed = applier.apply(recovered.transaction)
    assert resumed.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert len(resumed.idempotent) == projection_sequence - 1
    assert len(resumed.applied) == 13 - projection_sequence
    assert len(recovered.applied_ledger.records()) == 12
    assert _projection_authority(recovered.environment) == _projection_authority(control.environment)
