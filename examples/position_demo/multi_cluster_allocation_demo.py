from _support import RUNTIME, A, B, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionAllocationManager, OnlyPositionManager

positions = OnlyPositionManager(RUNTIME)
allocations = OnlyPositionAllocationManager(RUNTIME)
for item in (
    make_trade(1, OnlyOrderSide.BUY, "100", "10", cluster=A, settled=True),
    make_trade(2, OnlyOrderSide.BUY, "200", "12", cluster=B, settled=True),
):
    positions.apply_trade(item)
    allocations.apply_trade(item)
print(
    [
        (str(item.key.cluster_id), item.total_quantity.value, item.average_open_price.value)
        for item in allocations.snapshot_all()
    ]
)
