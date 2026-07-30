from onlyalpha.fee import OnlyOrderFeeAccrualManager
from tests.execution.support.order_fee_accrual import only_test_order_fee_accrual_steps


def test_order_fee_accrual_manager_checkpoint_round_trip_and_continuation() -> None:
    first, second = only_test_order_fee_accrual_steps(("5.00", "5.00"))
    manager = OnlyOrderFeeAccrualManager()
    manager.restore(first.after)
    payload = manager.capture_checkpoint()
    restored = OnlyOrderFeeAccrualManager()
    restored.restore_checkpoint(payload)
    assert restored.get(first.after.order_id) == first.after
    restored.restore(second.after)
    assert restored.get(first.after.order_id) == second.after
