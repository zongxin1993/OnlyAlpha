from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.market.runtime_rules import OnlyMarginInstruction


def instruction(
    action: str, order: str, amount: str, maintenance: str, *, trade: str = "", at: int = 1
) -> OnlyMarginInstruction:
    return OnlyMarginInstruction(
        action, "account", "600000.XSHG", "CNY", Decimal(amount), Decimal(maintenance), order, trade, OnlyTimestamp(at)
    )


def test_cancel_releases_only_the_named_orders_unfilled_reservation() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("runtime"))
    manager.apply(instruction("RESERVE", "opening-a", "100", "0"))
    manager.apply(instruction("OCCUPY", "opening-a", "50", "40", trade="fill-a", at=2))
    manager.apply(instruction("RESERVE", "opening-b", "30", "0", at=3))
    manager.apply(instruction("RELEASE", "opening-b", "30", "0", at=4))
    first = manager.get("opening-a")
    second = manager.get("opening-b")
    assert first is not None and second is not None
    assert (first.reserved, first.occupied) == (Decimal("50"), Decimal("50"))
    assert second.reserved == 0


def test_close_never_consumes_another_orders_unfilled_reservation() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("runtime"))
    manager.apply(instruction("RESERVE", "opening-a", "100", "0"))
    manager.apply(instruction("OCCUPY", "opening-a", "50", "40", trade="fill-a", at=2))
    manager.apply(instruction("RELEASE", "closing", "25", "20", trade="close-trade", at=3))
    state = manager.get("opening-a")
    assert state is not None
    assert (state.reserved, state.occupied, state.maintenance_required) == (Decimal("50"), Decimal("25"), Decimal("20"))
