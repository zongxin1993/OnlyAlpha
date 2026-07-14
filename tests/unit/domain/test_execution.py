from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager


def test_order_request_and_snapshot_are_immutable_and_serializable(
    instrument_id: OnlyInstrumentId,
) -> None:
    request = OnlyOrderRequest(
        OnlyOrderRequestId("request-1"),
        instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("2"), 0),
        OnlyTimeInForce.GTC,
        price=OnlyPrice(Decimal("10.00"), 2),
    )
    runtime_id = OnlyRuntimeId("runtime-1")
    manager = OnlyOrderManager(
        OnlyEngineId("engine-1"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )
    result = manager.create_order(
        request,
        OnlyClusterId("cluster-1"),
        OnlyAccountId("account-1"),
        OnlyTimestamp.from_unix_nanos(1),
    )
    assert result.snapshot.status is OnlyOrderStatus.CREATED
    assert OnlyOrderSnapshot.from_json(result.snapshot.to_json()) == result.snapshot
    with pytest.raises(FrozenInstanceError):
        result.snapshot.version = 2  # type: ignore[misc]


def test_limit_and_gtd_requests_require_prices_and_expiry(instrument_id: OnlyInstrumentId) -> None:
    with pytest.raises(OnlyValidationError):
        OnlyOrderRequest(
            OnlyOrderRequestId("request-2"),
            instrument_id,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTD,
        )
