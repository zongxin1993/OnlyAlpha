"""Shared deterministic Risk demo harness and ACCEPT example."""

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from onlyalpha.core.clock import OnlyBacktestClock, OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyMarketType, OnlyOrderSide, OnlyOrderType, OnlySessionType
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
class OnlyRiskDemoHarness:
    manager: OnlyOrderManager
    orders: OnlyOrderService
    risk: OnlyRiskService
    execution: OnlyPlaceholderExecutionService
    order_publisher: OnlyInMemoryOrderEventPublisher
    request: OnlyOrderRequest
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId


def only_risk_demo_harness(
    profile: OnlyRiskProfile | None = None,
    *,
    cluster_id: str = "risk-demo-cluster",
    runtime_id: str = "risk-demo-runtime",
) -> OnlyRiskDemoHarness:
    engine_id = OnlyEngineId("risk-demo-engine")
    typed_runtime_id = OnlyRuntimeId(runtime_id)
    typed_cluster_id = OnlyClusterId(cluster_id)
    account_id = OnlyAccountId("risk-demo-account")
    instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    cny = OnlyCurrency("CNY", 2)
    instrument = OnlyEquity(
        instrument_id=instrument_id,
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
    )
    clock = OnlyBacktestClock(1)
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("RISK-DEMO"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("full", time(0), time(0), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    manager = OnlyOrderManager(
        engine_id,
        typed_runtime_id,
        OnlySequenceOrderIdGenerator(typed_runtime_id),
        OnlySequenceClientOrderIdGenerator(typed_runtime_id),
    )
    risk = OnlyRiskService(
        engine_id,
        typed_runtime_id,
        OnlyClockView(clock),
        calendar,
        OnlyInstrumentRiskMappingView({instrument_id: instrument}),
        OnlyMarketRuleRiskMappingView({}),
        OnlyOrderQueryService(manager),
        OnlyInMemoryRiskEventPublisher(),
    )
    risk.bind_cluster_profile(
        typed_cluster_id,
        account_id,
        profile or OnlyRiskProfile(OnlyRiskProfileId("risk-demo-default")),
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
    request = OnlyOrderRequest(
        OnlyOrderRequestId("risk-demo-request-1"),
        instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("100"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )
    return OnlyRiskDemoHarness(
        manager,
        orders,
        risk,
        execution,
        order_publisher,
        request,
        typed_cluster_id,
        account_id,
    )


if __name__ == "__main__":
    demo = only_risk_demo_harness()
    result = demo.orders.submit(demo.request, demo.cluster_id, demo.account_id)
    print(
        result.risk_decision.outcome.value, result.snapshot.status.value, len(demo.risk.reservations.snapshot_active())
    )
