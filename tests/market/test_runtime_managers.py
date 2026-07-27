from datetime import date
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.margin import OnlyMarginManager
from onlyalpha.market.runtime_rules import OnlyMarginInstruction, OnlySettlementRuntimeInstruction
from onlyalpha.settlement import OnlySettlementManager


def test_settlement_manager_tracks_four_independent_availability_dimensions() -> None:
    manager = OnlySettlementManager()
    t0 = OnlyTradingDay(date(2026, 7, 17))
    t1 = OnlyTradingDay(date(2026, 7, 20))
    manager.register(
        OnlySettlementRuntimeInstruction(
            "settle-1", "TEST.XSHG", "trade-1", Decimal(100), Decimal(1000), t1, t0, t1, t1
        )
    )
    today = manager.advance(t0)[0]
    assert today.booked_quantity == Decimal(100)
    assert today.available_quantity == 0
    assert today.trade_available_cash == Decimal(1000)
    assert today.withdrawable_cash == 0
    settled = manager.advance(t1)[0]
    assert settled.available_quantity == Decimal(100)
    assert settled.withdrawable_cash == Decimal(1000)
    assert settled.legal_settled


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
