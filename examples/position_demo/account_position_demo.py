from _support import RUNTIME, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionManager

manager = OnlyPositionManager(RUNTIME)
manager.apply_trade(make_trade(1, OnlyOrderSide.BUY, "100", "10", settled=True))
manager.apply_trade(make_trade(2, OnlyOrderSide.BUY, "200", "12", settled=True))
snapshot = manager.list_open()[0]
print(snapshot.total_quantity.value, snapshot.average_open_price.value if snapshot.average_open_price else None)
