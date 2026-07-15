from _support import RUNTIME, apply, create, trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionAllocationManager

manager, key = create()
apply(manager, key, OnlyPositionAllocationManager(RUNTIME), trade(1, OnlyOrderSide.BUY, "1000", "10.00", "5.00"))
print(manager.require_snapshot(key).cash)
