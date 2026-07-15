from decimal import Decimal

from _support import ACCOUNT, CNY, INSTRUMENT, RUNTIME, make_trade

from onlyalpha.domain.enums import OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position import (
    OnlyBrokerPositionSnapshot,
    OnlyGatewayId,
    OnlyPositionAllocationManager,
    OnlyPositionAuthorityPolicy,
    OnlyPositionManager,
    OnlyPositionReconciliationService,
    OnlyPositionSide,
)

positions = OnlyPositionManager(RUNTIME)
allocations = OnlyPositionAllocationManager(RUNTIME)
opening = make_trade(1, OnlyOrderSide.BUY, "1000", "10", settled=True)
positions.apply_trade(opening)
allocations.apply_trade(opening)
broker = OnlyBrokerPositionSnapshot(
    OnlyGatewayId("demo-gateway"),
    ACCOUNT,
    INSTRUMENT,
    OnlyPositionSide.LONG,
    OnlyQuantity(Decimal("800"), 0),
    OnlyQuantity(Decimal("800"), 0),
    OnlyQuantity(Decimal("0"), 0),
    OnlyQuantity(Decimal("800"), 0),
    OnlyQuantity(Decimal("0"), 0),
    OnlyQuantity(Decimal("0"), 0),
    OnlyQuantity(Decimal("800"), 0),
    OnlyPrice(Decimal("10.00"), 2),
    OnlyMoney(Decimal("8000.00"), CNY),
    opening.ts_event,
    1,
)
result = OnlyPositionReconciliationService(
    RUNTIME, positions, allocations, OnlyPositionAuthorityPolicy(OnlyRuntimeMode.LIVE)
).reconcile(broker)
print(result.severity.value, result.local.status.value if result.local else None)
