from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.reducers.trade_fee_accrual import (
    OnlyOrderFeeAccrualTradeReducer,
    OnlyOrderFeeAccrualTradeReduction,
)
from onlyalpha.fee import OnlyFeeCalculationScope, OnlyFeeTargetComponent
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def only_test_order_fee_accrual_steps(
    targets: tuple[str, ...],
    *,
    scope: OnlyFeeCalculationScope = OnlyFeeCalculationScope.ORDER_CUMULATIVE,
    raw_amounts: tuple[str, ...] | None = None,
) -> tuple[OnlyOrderFeeAccrualTradeReduction, ...]:
    context = only_test_generic_t0_trade_planning_context()
    planned_trade = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    currency = context.fee_assessment.total_charges.currency
    base_component = context.fee_assessment.components[0]
    reducer = OnlyOrderFeeAccrualTradeReducer()
    before = None
    results = []
    cumulative_quantity = Decimal(0)
    cumulative_notional = Decimal(0)
    for index, target_text in enumerate(targets, start=1):
        quantity = OnlyQuantity(Decimal(1), planned_trade.quantity.precision)
        notional = OnlyMoney(Decimal("10.00"), currency)
        cumulative_quantity += quantity.value
        cumulative_notional += notional.amount
        trade_id = OnlyTradeId(f"accrual-trade-{index}")
        trade = replace(
            planned_trade,
            trade_id=trade_id,
            quantity=quantity,
            gross_notional=notional,
            settled_notional=notional,
        )
        raw_text = target_text if raw_amounts is None else raw_amounts[index - 1]
        identity = replace(base_component.identity, calculation_scope=scope)
        component = OnlyFeeTargetComponent(
            identity,
            OnlyMoney(Decimal(raw_text), currency),
            OnlyMoney(Decimal(target_text), currency),
            OnlyMoney(Decimal(target_text), currency),
            context.fee_assessment.local_finality,
        )
        assessment = replace(
            context.fee_assessment,
            assessment_id=f"{index:064x}",
            trade_id=trade_id,
            components=(component,),
            total_charges=component.target_amount,
        )
        result = reducer.reduce(
            before,
            assessment,
            trade,
            cumulative_fill_quantity=OnlyQuantity(cumulative_quantity, quantity.precision),
            cumulative_fill_notional=OnlyMoney(cumulative_notional, currency),
            order_fixed_policy_fingerprint=assessment.binding.fingerprint,
            projection_sequence=6,
        )
        results.append(result)
        before = result.after
    return tuple(results)


__all__ = ["only_test_order_fee_accrual_steps"]
