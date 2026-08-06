from onlyalpha.execution import (
    OnlyOrderFeeAccrualProjection,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionBatchStatus,
    OnlyRuntimeProjectionComponent,
    only_decode_execution_projection,
    only_encode_execution_projection,
)
from tests.execution.targets.support import only_test_projection_target_bundle


def test_order_fee_accrual_projection_has_independent_component_codec_and_replays() -> None:
    bundle = only_test_projection_target_bundle()
    projection = next(
        item
        for item in bundle.transaction.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL
    )
    assert isinstance(projection, OnlyOrderFeeAccrualProjection)
    assert only_decode_execution_projection(only_encode_execution_projection(projection)) == projection

    applier = OnlyRuntimeProjectionApplier(bundle.targets)
    first = applier.apply(bundle.transaction)
    replay = applier.apply(bundle.transaction)
    assert first.status is replay.status is OnlyRuntimeProjectionBatchStatus.COMPLETED
    assert bundle.environment.runtime.order_fee_accrual_manager.get(projection.after.order_id) == projection.after
    assert len(replay.idempotent) == len(bundle.transaction.projections)
