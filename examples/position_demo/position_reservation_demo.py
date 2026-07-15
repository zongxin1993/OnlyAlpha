from decimal import Decimal

from _support import ACCOUNT, INSTRUMENT, RUNTIME, A, make_trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.position import OnlyPositionAllocationManager, OnlyPositionManager, OnlyPositionReservationManager

positions = OnlyPositionManager(RUNTIME)
allocations = OnlyPositionAllocationManager(RUNTIME)
opening = make_trade(1, OnlyOrderSide.BUY, "1000", "10", settled=True)
positions.apply_trade(opening)
allocations.apply_trade(opening)
reservations = OnlyPositionReservationManager(RUNTIME, positions, allocations)
reservations.create(
    ACCOUNT, A, INSTRUMENT, OnlyOrderId("sell-1"), OnlyQuantity(Decimal("700"), 0), OnlyTimestamp(2_000)
)
print(positions.list_open()[0].available_quantity.value)
