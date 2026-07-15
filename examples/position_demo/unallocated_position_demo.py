from _support import RUNTIME, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionAllocationManager

allocations = OnlyPositionAllocationManager(RUNTIME)
allocations.apply_trade(make_trade(1, OnlyOrderSide.BUY, "300", "10", cluster=None, settled=True))
print(allocations.unallocated()[0].total_quantity.value)
