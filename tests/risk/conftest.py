from dataclasses import dataclass
from datetime import time
from decimal import Decimal

import pytest

from onlyalpha.core.clock import OnlyBacktestClock, OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyMarketType,
    OnlyOrderSide,
    OnlyOrderType,
    OnlySessionType,
)
from onlyalpha.domain.execution import OnlyOrderRequest
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
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.publisher import OnlyInMemoryRiskEventPublisher
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.views import OnlyInstrumentRiskMappingView, OnlyMarketRuleRiskMappingView


@dataclass(slots=True)
class OnlyRiskHarness:
    clock: OnlyBacktestClock
    calendar: OnlyTradingCalendar
    instrument: OnlyEquity
    manager: OnlyOrderManager
    execution: OnlyPlaceholderExecutionService
    order_publisher: OnlyInMemoryOrderEventPublisher
    risk_publisher: OnlyInMemoryRiskEventPublisher
    risk: OnlyRiskService
    orders: OnlyOrderService
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId


@pytest.fixture
def instrument() -> OnlyEquity:
    cny = OnlyCurrency("CNY", 2)
    return OnlyEquity(
        instrument_id=OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=cny,
        settlement_currency=cny,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.05"), 2),
        step_size=OnlyQuantity(Decimal("100"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        minimum_quantity=OnlyQuantity(Decimal("100"), 0),
        maximum_quantity=OnlyQuantity(Decimal("10000"), 0),
    )


@pytest.fixture
def order_request(instrument: OnlyEquity) -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId("risk-request-1"),
        instrument.instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("100"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )


@pytest.fixture
def build_harness(instrument: OnlyEquity):
    def build(
        profile: OnlyRiskProfile | None = None,
        *,
        runtime_id: str = "risk-runtime",
        cluster_id: str = "risk-cluster",
    ) -> OnlyRiskHarness:
        typed_runtime_id = OnlyRuntimeId(runtime_id)
        typed_cluster_id = OnlyClusterId(cluster_id)
        account_id = OnlyAccountId("risk-account")
        clock = OnlyBacktestClock(1)
        calendar = OnlyTradingCalendar(
            OnlyCalendarId("RISK"),
            OnlyVenueId("XSHG"),
            OnlyTimeZone("UTC"),
            (OnlyTradingSession("full", time(0), time(0), OnlySessionType.CONTINUOUS),),
            weekend_days=(),
        )
        manager = OnlyOrderManager(
            OnlyEngineId("engine"),
            typed_runtime_id,
            OnlySequenceOrderIdGenerator(typed_runtime_id),
            OnlySequenceClientOrderIdGenerator(typed_runtime_id),
        )
        query = OnlyOrderQueryService(manager)
        risk_publisher = OnlyInMemoryRiskEventPublisher()
        risk = OnlyRiskService(
            OnlyEngineId("engine"),
            typed_runtime_id,
            OnlyClockView(clock),
            calendar,
            OnlyInstrumentRiskMappingView({instrument.instrument_id: instrument}),
            OnlyMarketRuleRiskMappingView({}),
            query,
            risk_publisher,
        )
        risk.bind_cluster_profile(
            typed_cluster_id,
            account_id,
            profile or OnlyRiskProfile(OnlyRiskProfileId("default")),
        )
        execution = OnlyPlaceholderExecutionService()
        order_publisher = OnlyInMemoryOrderEventPublisher()
        orders = OnlyOrderService(
            manager,
            execution,
            order_publisher,
            lambda: OnlyTimestamp.from_unix_nanos(clock.timestamp_ns()),
            risk,
            risk.make_evaluation_context,
        )
        return OnlyRiskHarness(
            clock,
            calendar,
            instrument,
            manager,
            execution,
            order_publisher,
            risk_publisher,
            risk,
            orders,
            typed_cluster_id,
            account_id,
        )

    return build
