from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.reducers.trade_fee_accrual import (
    OnlyOrderFeeAccrualTradeReducer,
    OnlyOrderFeeAccrualTradeReduction,
)
from onlyalpha.fee import (
    OnlyFeeAuthority,
    OnlyFeeBreakdown,
    OnlyFeeCalculationScope,
    OnlyFeeComponent,
    OnlyFeeStatus,
    OnlyFeeType,
)
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def only_test_order_fee_accrual_steps(
    targets: tuple[str, ...],
    *,
    scope: OnlyFeeCalculationScope = OnlyFeeCalculationScope.ORDER_CUMULATIVE,
    raw_amounts: tuple[str, ...] | None = None,
) -> tuple[OnlyOrderFeeAccrualTradeReduction, ...]:
    context = only_test_generic_t0_trade_planning_context()
    base_trade = context.update.fill
    planned_trade = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    currency = context.fee_instruction.fee_breakdown.currency
    reducer = OnlyOrderFeeAccrualTradeReducer()
    before = None
    results = []
    for index, target in enumerate(targets, start=1):
        quantity = OnlyQuantity(Decimal("1"), base_trade.quantity.precision)
        notional = OnlyMoney(Decimal("10.00"), currency)
        trade = replace(
            planned_trade,
            trade_id=OnlyTradeId(f"accrual-trade-{index}"),
            quantity=quantity,
            gross_notional=notional,
            settled_notional=notional,
        )
        raw = target if raw_amounts is None else raw_amounts[index - 1]
        component = OnlyFeeComponent(
            fee_type=OnlyFeeType.BROKER_COMMISSION,
            authority=OnlyFeeAuthority.BROKER,
            amount=OnlyMoney(Decimal(target), currency),
            status=OnlyFeeStatus.CONFIRMED,
            source_id="test-broker",
            schedule_id="test-order-fee",
            schedule_version="1",
            metadata={"raw_amount": raw},
            calculation_scope=scope,
        )
        breakdown = OnlyFeeBreakdown(
            currency,
            (component,),
            component.amount,
            OnlyFeeStatus.CONFIRMED,
        )
        instruction = replace(
            context.fee_instruction,
            trade_id=str(trade.trade_id),
            fee_breakdown=breakdown,
            idempotency_key=f"accrual:{index}",
        )
        result = reducer.reduce(before, instruction, trade, projection_sequence=5)
        results.append(result)
        before = result.after
    return tuple(results)


__all__ = ["only_test_order_fee_accrual_steps"]
