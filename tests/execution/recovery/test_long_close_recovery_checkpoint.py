from onlyalpha.position import OnlyPositionAllocationManager, OnlyPositionManager, OnlyPositionReservationManager
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_long_close_checkpoint_restores_consumed_position_reservation_authority() -> None:
    environment, context, _ = only_test_generic_t0_long_close_context()
    result = environment.runtime.execution_processor.process(context.update)
    assert result.status.value == "APPLIED"
    source = environment.runtime.position_reservation_manager
    expected = source.get(context.update.order_id)
    assert expected is not None and expected.remaining_quantity.value == 0

    restored = OnlyPositionReservationManager(
        environment.runtime.config.runtime_id,
        OnlyPositionManager(environment.runtime.config.runtime_id),
        OnlyPositionAllocationManager(environment.runtime.config.runtime_id),
    )
    restored.restore_checkpoint(source.capture_checkpoint())

    assert restored.get(context.update.order_id) == expected
    assert restored.capture_checkpoint() == source.capture_checkpoint()
