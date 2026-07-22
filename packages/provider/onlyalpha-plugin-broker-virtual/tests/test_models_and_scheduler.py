from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual import (
    OnlyFixedLatencyModel,
    OnlyFixedSlippageModel,
    OnlyVirtualBrokerScheduler,
)

from onlyalpha.broker import OnlyBoundedBrokerInboundQueue
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.value import OnlyPrice


def test_slippage_and_latency_are_independent_exact_models() -> None:
    slipped = OnlyFixedSlippageModel(OnlyPrice(Decimal("0.01"), 2)).apply(
        OnlyOrderSide.BUY, OnlyPrice(Decimal("10.00"), 2)
    )
    latency = OnlyFixedLatencyModel(1, 2, 3, 4, 5)

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
        OnlyBoundedBrokerInboundQueue(0)
