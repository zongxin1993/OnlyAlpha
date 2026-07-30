from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner
from onlyalpha.fee import OnlyOrderFeeAccrualManager
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from tests.integration_demo.environment import DAY_ONE


def test_checkpoint_round_trip_preserves_multi_fill_before_authority_for_next_fill() -> None:
    scenario = OnlyTestGenericT0Scenario("checkpoint-three-fill")
    env = _environment(scenario)
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    submitted = env.submit_buy(request_id="checkpoint-three-fill", quantity="1000")
    assert submitted.order_id is not None

    for index, quantity in enumerate(("300", "400"), start=1):
        update = _trade_update(env, scenario, suffix=str(index), fill_price="9.90")
        update = replace(update, fill=replace(update.fill, quantity=OnlyQuantity(Decimal(quantity), 0)))
        assert env.runtime.execution_processor.process(update).status.value == "APPLIED"

    third = _trade_update(env, scenario, suffix="3", fill_price="9.90")
    third = replace(third, fill=replace(third.fill, quantity=OnlyQuantity(Decimal("300"), 0)))
    context = only_test_real_trade_planning_context(env, third)
    restored_accrual = OnlyOrderFeeAccrualManager()
    restored_accrual.restore_checkpoint(env.runtime.order_fee_accrual_manager.capture_checkpoint())
    restored_context = replace(
        context,
        order_before=type(context.order_before).from_json(context.order_before.to_json()),
        position_before=type(context.position_before).from_json(context.position_before.to_json()),
        allocation_before=type(context.allocation_before).from_json(context.allocation_before.to_json()),
        account_before=type(context.account_before).from_json(context.account_before.to_json()),
        strategy_ledger_before=type(context.strategy_ledger_before).from_json(context.strategy_ledger_before.to_json()),
        account_cash_reservation_before=type(context.account_cash_reservation_before).from_json(
            context.account_cash_reservation_before.to_json()
        ),
        strategy_cash_reservation_before=type(context.strategy_cash_reservation_before).from_json(
            context.strategy_cash_reservation_before.to_json()
        ),
        risk_reservation_before=type(context.risk_reservation_before).from_json(
            context.risk_reservation_before.to_json()
        ),
        risk_before=type(context.risk_before).from_json(context.risk_before.to_json()),
        order_fee_accrual_before=restored_accrual.get(submitted.order_id),
    )
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(restored_context)
    assert prepared.fact_draft.fill_index == 3
    assert prepared.fact_draft.order_cumulative_fee_after.amount == Decimal("9.90")
    assert prepared.fact_draft.position_cumulative_open_price_quantity_after == Decimal("9900.00")
    assert prepared.fact_draft.terminal_fill
