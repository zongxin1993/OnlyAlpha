from _support import RUNTIME, apply, create, trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionAllocationManager

manager, key = create()
allocations = OnlyPositionAllocationManager(RUNTIME)
apply(manager, key, allocations, trade(1, OnlyOrderSide.BUY, "1000", "10.00", "5.00"))
apply(manager, key, allocations, trade(2, OnlyOrderSide.SELL, "400", "12.00", "3.00"))
print(manager.require_snapshot(key).pnl)
