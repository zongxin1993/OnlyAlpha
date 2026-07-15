from datetime import date

from _support import ACCOUNT, RUNTIME, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.position import OnlyPositionAllocationManager, OnlyPositionManager, OnlySettlementService

positions = OnlyPositionManager(RUNTIME)
allocations = OnlyPositionAllocationManager(RUNTIME)
for item in (
    make_trade(1, OnlyOrderSide.BUY, "1000", "10", settled=True),
    make_trade(2, OnlyOrderSide.BUY, "500", "11"),
):
    positions.apply_trade(item)
    allocations.apply_trade(item)
before = positions.list_open()[0]
print("before", before.settled_quantity.value, before.unsettled_quantity.value, before.available_quantity.value)
OnlySettlementService(positions, allocations).settle_account(
    ACCOUNT, OnlyTradingDay(date(2026, 7, 15)), OnlyTradingDay(date(2026, 7, 16))
)
print("after", positions.list_open()[0].settled_quantity.value)
