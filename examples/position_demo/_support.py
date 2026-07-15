from decimal import Decimal

from onlyalpha.domain.enums import OnlyCurrencyType, OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position import OnlyPositionSide, OnlyPositionTrade, OnlySettlementBucket

RUNTIME = OnlyRuntimeId("position-demo")
ACCOUNT = OnlyAccountId("demo-account")
A = OnlyClusterId("cluster-a")
B = OnlyClusterId("cluster-b")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
CNY = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)


def make_trade(
    sequence: int,
    side: OnlyOrderSide,
    quantity: str,
    price: str,
    *,
    cluster: OnlyClusterId | None = A,
    settled: bool = False,
) -> OnlyPositionTrade:
    timestamp = OnlyTimestamp(sequence * 1_000)
    return OnlyPositionTrade(
        OnlyTradeId(f"trade-{sequence}"),
        None,
        OnlyOrderId(f"order-{sequence}"),
        cluster,
        RUNTIME,
        ACCOUNT,
        INSTRUMENT,
        side,
        OnlyDirection.BUY if side is OnlyOrderSide.BUY else OnlyDirection.SELL,
        OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
        OnlyPositionSide.LONG,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyMoney(Decimal("0.00"), CNY),
        timestamp,
        timestamp,
        sequence,
        settlement_bucket=(OnlySettlementBucket.SETTLED if settled else OnlySettlementBucket.UNSETTLED),
    )
