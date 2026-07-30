from pathlib import Path

from onlyalpha.execution import OnlyExecutionProjectionComponent, OnlyExecutionProjectionOrder


def test_long_close_is_routed_to_prepared_transaction_without_parallel_entrypoint() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    planner = Path("src/onlyalpha/execution/trade_planner.py").read_text(encoding="utf-8")

    assert "supported_close" in processor
    assert "order.side is OnlyOrderSide.SELL" in processor
    assert "order.offset is OnlyOffset.CLOSE" in processor
    assert "(supported_open or supported_close)" in processor
    assert "if isinstance(update, OnlyBrokerTradeUpdate) and self._uses_prepared_trade_path" in processor
    assert "OnlyTradeExecutionTransactionPlanner" in planner
    assert "OnlyLongClose" not in processor + planner


def test_long_close_projection_order_is_one_fixed_global_order() -> None:
    components = (
        OnlyExecutionProjectionComponent.ORDER,
        OnlyExecutionProjectionComponent.POSITION,
        OnlyExecutionProjectionComponent.ALLOCATION,
        OnlyExecutionProjectionComponent.SETTLEMENT,
        OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL,
        OnlyExecutionProjectionComponent.FEE,
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
        OnlyExecutionProjectionComponent.POSITION_RESERVATION,
        OnlyExecutionProjectionComponent.RISK_RESERVATION,
        OnlyExecutionProjectionComponent.RISK,
        OnlyExecutionProjectionComponent.VALUATION,
    )

    assert tuple(OnlyExecutionProjectionOrder[item.name] for item in components) == tuple(
        sorted(OnlyExecutionProjectionOrder[item.name] for item in components)
    )


def test_position_reservation_is_a_formal_projection_target_and_checkpoint_participant() -> None:
    targets = Path("src/onlyalpha/execution/projection_targets.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")

    assert "class OnlyPositionReservationExecutionProjectionTarget" in targets
    assert "OnlyExecutionProjectionComponent.POSITION_RESERVATION" in targets
    assert '"position-reservation.authority"' in runtime
