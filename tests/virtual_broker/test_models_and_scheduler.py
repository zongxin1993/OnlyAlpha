from decimal import Decimal

import pytest

from onlyalpha.broker.virtual import (
    OnlyCnEquityCommissionModel,
    OnlyFixedLatencyModel,
    OnlyFixedSlippageModel,
    OnlyVirtualBrokerScheduler,
    OnlyVirtualBrokerUpdateQueue,
)
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate

CNY = OnlyCurrency("CNY", 2)


def test_commission_slippage_and_latency_are_independent_exact_models() -> None:
    commission = OnlyCnEquityCommissionModel(
        OnlyRate(Decimal("0.0003"), 4),
        OnlyMoney(Decimal("5.00"), CNY),
        OnlyRate(Decimal("0.0005"), 4),
        OnlyRate(Decimal("0.00001"), 5),
    )
    fee = commission.calculate(
        OnlyOrderSide.SELL,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("1000"), 0),
        CNY,
    )
    slipped = OnlyFixedSlippageModel(OnlyPrice(Decimal("0.01"), 2)).apply(
        OnlyOrderSide.BUY, OnlyPrice(Decimal("10.00"), 2)
    )
    latency = OnlyFixedLatencyModel(1, 2, 3, 4, 5)

    assert fee == OnlyMoney(Decimal("10.10"), CNY)
    assert slipped == OnlyPrice(Decimal("10.01"), 2)
    assert latency.fill_latency_ns == 3


def test_scheduler_is_stable_and_queue_is_bounded() -> None:
    observed: list[int] = []
    scheduler = OnlyVirtualBrokerScheduler()
    scheduler.schedule(2, lambda: observed.append(2))
    scheduler.schedule(1, lambda: observed.append(1))
    scheduler.schedule(2, lambda: observed.append(3))

    assert scheduler.run_due(2) == 3
    assert observed == [1, 2, 3]

    with pytest.raises(ValueError):
        OnlyVirtualBrokerUpdateQueue(0)
