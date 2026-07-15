from decimal import Decimal

from _support import INSTRUMENT, RUNTIME, A, apply, create, trade

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMultiplier, OnlyPrice
from onlyalpha.position import OnlyPositionAllocationManager
from onlyalpha.strategy_ledger.models import OnlyStrategyMarkPrice
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService

manager, key = create()
allocations = OnlyPositionAllocationManager(RUNTIME)
apply(manager, key, allocations, trade(1, OnlyOrderSide.BUY, "1000", "10.00", "5.00"))
valuation = OnlyStrategyValuationService().value(
    key,
    allocations.list_by_cluster(A),
    (OnlyStrategyMarkPrice(INSTRUMENT, OnlyPrice(Decimal("11.00"), 2), 1, "DEMO"),),
    {INSTRUMENT: OnlyMultiplier(Decimal(1), 0)},
    OnlyTimestamp(2_000),
    OnlyTimestamp(2_000),
    1,
)
manager.apply_valuation(valuation)
print(manager.require_snapshot(key).equity)
