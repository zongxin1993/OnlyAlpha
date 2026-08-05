from dataclasses import replace
from datetime import date, timedelta

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.execution.trade_planner import OnlyTradeExecutionTransactionPlanner
from onlyalpha.market.models import OnlySettlementModel, OnlySettlementRule, OnlySettlementTiming
from onlyalpha.settlement.models import OnlySettlementScheduleRequest
from onlyalpha.transaction.projection import OnlySettlementExecutionProjection
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def _next_business_day(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
    value = day.value
    for _ in range(lag):
        value += timedelta(days=1)
        while value.weekday() >= 5:
            value += timedelta(days=1)
    return OnlyTradingDay(value)


def _ashare_settlement_model() -> OnlySettlementModel:
    return OnlySettlementModel(
        "CN_A_SHARE_T1",
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ZERO),
    )


def test_ashare_schedule_separates_trade_availability_and_withdrawal_across_weekend() -> None:
    friday = OnlyTradingDay(date(2026, 8, 7))
    schedule = _ashare_settlement_model().schedule(
        OnlySettlementScheduleRequest(OnlyOrderSide.SELL, friday), _next_business_day
    )
    assert schedule.cash_trade_available_on == friday
    assert schedule.cash_withdrawable_on == OnlyTradingDay(date(2026, 8, 10))
    assert schedule.asset_trade_available_on == OnlyTradingDay(date(2026, 8, 10))


def test_trade_planner_freezes_final_instruction_and_lifecycle_identity() -> None:
    context = only_test_generic_t0_trade_planning_context()
    schedule = _ashare_settlement_model().schedule(
        OnlySettlementScheduleRequest(
            context.order_before.side,
            context.trade_instruction.settlement_schedule.asset_booked_on,
        ),
        _next_business_day,
    )
    context = replace(
        context,
        trade_instruction=replace(context.trade_instruction, settlement_schedule=schedule),
    )
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    projection = next(item for item in prepared.projections if isinstance(item, OnlySettlementExecutionProjection))
    instruction = projection.after.instruction
    assert instruction is not None
    assert instruction.trade_id == context.update.fill.trade_id
    assert str(instruction.position_id)
    assert instruction.position_cycle > 0
    assert instruction.allocation_cycle > 0
    assert instruction.schedule.asset_trade_available_on > instruction.trading_day
