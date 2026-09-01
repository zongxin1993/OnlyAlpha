from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.execution import OnlySettlementExecutionProjection
from onlyalpha.execution.trade_planner import OnlyTradeExecutionTransactionPlanner
from onlyalpha.margin import OnlyMarginManager
from onlyalpha.market.models import OnlySettlementModel, OnlySettlementRule, OnlySettlementTiming
from onlyalpha.market.runtime_rules import OnlyMarginInstruction
from onlyalpha.settlement import OnlySettlementAuthority, OnlySettlementScheduleRequest
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_settlement_authority_tracks_four_independent_availability_dimensions() -> None:
    context = only_test_generic_t0_trade_planning_context()
    t0 = context.trading_day

    def next_business_day(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
        value = day.value
        for _ in range(lag):
            value += timedelta(days=1)
            while value.weekday() >= 5:
                value += timedelta(days=1)
        return OnlyTradingDay(value)

    t1 = next_business_day(t0, 1)

    model = OnlySettlementModel(
        "CN_A_SHARE_T1",
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE),
        OnlySettlementRule(OnlySettlementTiming.T_PLUS_ZERO),
    )
    schedule = model.schedule(OnlySettlementScheduleRequest(context.order_before.side, t0), next_business_day)
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(
        replace(
            context,
            trading_day=t0,
            trade_instruction=replace(context.trade_instruction, settlement_schedule=schedule),
        )
    )
    projection = next(item for item in prepared.projections if isinstance(item, OnlySettlementExecutionProjection))
    assert projection.after.instruction is not None
    manager = OnlySettlementAuthority()
    manager.register(projection.after.instruction)

    today = manager.snapshots()[0]
    assert not today.asset_trade_available
    assert today.cash_trade_available
    assert not today.cash_withdrawable
    assert not today.legal_settled
    assert {item.transition.value for item in manager.due_transitions(t1)} == {
        "ASSET_TRADE_AVAILABLE",
        "CASH_WITHDRAWABLE",
        "LEGAL_SETTLED",
    }


def test_margin_manager_reserve_occupy_and_release_lifecycle() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("runtime-margin"))
    manager.apply(
        OnlyMarginInstruction(
            "RESERVE",
            "account-1",
            "FUTURE.X",
            "USD",
            Decimal(100),
            Decimal(80),
            "order-1",
            "trade-0",
            OnlyTimestamp(1),
        )
    )
    occupied = manager.apply(
        OnlyMarginInstruction(
            "OCCUPY",
            "account-1",
            "FUTURE.X",
            "USD",
            Decimal(100),
            Decimal(80),
            "order-1",
            "trade-1",
            OnlyTimestamp(2),
        )
    )
    assert occupied.reserved_after == 0
    assert occupied.occupied_after == Decimal(100)
    released = manager.apply(
        OnlyMarginInstruction(
            "RELEASE",
            "account-1",
            "FUTURE.X",
            "USD",
            Decimal(100),
            Decimal(80),
            "order-2",
            "trade-2",
            OnlyTimestamp(3),
        )
    )
    assert released.occupied_after == 0
    assert released.maintenance_required_after == 0
    authority = manager.get("order-1")
    assert authority is not None and authority.occupied == 0 and authority.released == Decimal(100)


def test_margin_manager_normalizes_formula_scale_to_currency_precision() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("runtime-margin-precision"))

    record = manager.apply(
        OnlyMarginInstruction(
            "RESERVE",
            "account-1",
            "FUTURE.X",
            "USD",
            Decimal("120.0000"),
            Decimal("80.005"),
            "order-precision",
            "",
            OnlyTimestamp(1),
        )
    )

    reservation = manager.get("order-precision")
    assert reservation is not None
    assert reservation.original_reserved == Decimal("120.00")
    assert reservation.maintenance_required == Decimal("0.00")
    assert record.amount == Decimal("120.00")
