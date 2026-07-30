from onlyalpha.execution import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyOrderFeeAccrualExecutionProjection,
    only_decode_execution_projection,
    only_encode_execution_projection,
)
from tests.execution.targets.support import only_test_projection_target_bundle


def test_order_fee_accrual_projection_has_independent_component_codec_and_replays() -> None:
    bundle = only_test_projection_target_bundle()
    projection = next(
        item
        for item in bundle.transaction.projections
        if item.identity.component is OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL
    )
    assert isinstance(projection, OnlyOrderFeeAccrualExecutionProjection)
    assert only_decode_execution_projection(only_encode_execution_projection(projection)) == projection

    applier = OnlyExecutionProjectionApplier(bundle.targets)
    first = applier.apply(bundle.transaction)
    replay = applier.apply(bundle.transaction)
    assert first.status is replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert bundle.environment.runtime.order_fee_accrual_manager.get(projection.after.order_id) == projection.after
    assert len(replay.idempotent) == len(bundle.transaction.projections)
