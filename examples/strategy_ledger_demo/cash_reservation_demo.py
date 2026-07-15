from decimal import Decimal

from _support import CNY, create

from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney

manager, key = create()
manager.reserve_cash(
    key,
    OnlyOrderId("demo-reservation"),
    OnlyMoney(Decimal("60000.00"), CNY),
    OnlyMoney(Decimal("10.00"), CNY),
    OnlyTimestamp(1),
)
print(manager.require_snapshot(key).cash)
manager.release_cash_reservation(key, OnlyOrderId("demo-reservation"), OnlyTimestamp(2))
print(manager.require_snapshot(key).cash)
