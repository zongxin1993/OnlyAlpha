from datetime import time
from decimal import Decimal

import pytest

from onlyalpha.core.clock import OnlyBacktestClock, OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyMarketType, OnlyOrderSide, OnlyOrderType, OnlySessionType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRawSymbol,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.publisher import OnlyNoOpRiskEventPublisher
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.views import OnlyInstrumentRiskMappingView

from ..runtime_support.common import only_demo_runtime


@pytest.fixture
def order_manager() -> OnlyOrderManager:
    runtime_id = OnlyRuntimeId("runtime")
    return OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )


@pytest.fixture
def make_runtime():
    return only_demo_runtime


@pytest.fixture
def order_request() -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId("request-1"),
        OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("4"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )


@pytest.fixture
def risk_service(order_manager: OnlyOrderManager, order_request: OnlyOrderRequest) -> OnlyRiskService:
    runtime_id = OnlyRuntimeId("runtime")
    clock = OnlyBacktestClock(1)
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("full", time(0), time(0), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    cny = OnlyCurrency("CNY", 2)
    instrument = OnlyEquity(
        instrument_id=order_request.instrument_id,
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=cny,
        settlement_currency=cny,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
    )
    service = OnlyRiskService(
        OnlyEngineId("engine"),
        runtime_id,
        OnlyClockView(clock),
        calendar,
        OnlyInstrumentRiskMappingView({instrument.instrument_id: instrument}),
        OnlyOrderQueryService(order_manager),
        OnlyNoOpRiskEventPublisher(),
    )
    service.bind_cluster_profile(
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyRiskProfile(OnlyRiskProfileId("default")),
    )
    return service


@pytest.fixture
def created_order(order_manager: OnlyOrderManager, order_request: OnlyOrderRequest):
    return order_manager.create_order(
        order_request,
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(1),
    )


def only_fill(order_id, trade_id: str, quantity: str, price: str, timestamp: int) -> OnlyOrderFill:
    return OnlyOrderFill(
        OnlyTradeId(trade_id),
        order_id,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyTimestamp.from_unix_nanos(timestamp),
        OnlyTimestamp.from_unix_nanos(timestamp),
    )
