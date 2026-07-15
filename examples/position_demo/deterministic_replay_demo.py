from _support import RUNTIME, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionManager

outputs = []
for _ in range(100):
    manager = OnlyPositionManager(RUNTIME)
    manager.apply_trade(make_trade(1, OnlyOrderSide.BUY, "100", "10", settled=True))
    manager.apply_trade(make_trade(2, OnlyOrderSide.SELL, "20", "12"))
    snapshot = manager.list_open()[0]
    outputs.append((str(snapshot.position_id), snapshot.total_quantity.value, snapshot.realized_pnl.amount))
print("deterministic", len(set(outputs)) == 1)
