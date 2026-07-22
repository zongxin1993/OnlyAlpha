"""Runtime composition helper for one authoritative fee calculation path."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.fee.engine import OnlyFeeEngine, OnlyFeeEstimate
from onlyalpha.fee.models import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeBreakdown,
    OnlyFeeCalculationRequest,
    OnlyFeeConfigurationMode,
    OnlyFeeInstruction,
    OnlyFeeStatus,
)
from onlyalpha.fee.schedules import OnlyMarketFeeSchedule, OnlyMarketFeeScheduleRegistry
from onlyalpha.market.runtime_rules import OnlyTradeInstructionPort


class OnlyFeeResolver:
    """Resolves estimates and fills with the same schedules and market identity."""

    def __init__(
        self,
        engine: OnlyFeeEngine,
        market_schedules: OnlyMarketFeeScheduleRegistry,
        market_rules: OnlyTradeInstructionPort | None,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay],
    ) -> None:
        self._engine = engine
        self._market_schedules = market_schedules
        self._market_rules = market_rules
        self._instruments = instruments
        self._trading_day = trading_day

    def estimate_order(self, order: OnlyOrderSnapshot, price: OnlyPrice, timestamp: OnlyTimestamp) -> OnlyFeeEstimate:
        request, schedule = self._request(
            order,
            trade_id=f"estimate:{order.order_id}",
            price=price,
            quantity=order.quantity.value,
            timestamp=timestamp,
            liquidity_role=None,
        )
        return self._engine.estimate(
            request,
            market_schedule=schedule,
            broker_schedule=None,
            market_mode=(OnlyFeeConfigurationMode.DEFAULT if schedule is not None else OnlyFeeConfigurationMode.NONE),
            broker_mode=OnlyFeeConfigurationMode.NONE,
        )

    def resolve_trade(
        self,
        order: OnlyOrderSnapshot,
        *,
        trade_id: str,
        price: OnlyPrice,
        quantity: Decimal,
        timestamp: OnlyTimestamp,
        liquidity_role: str | None,
        created_at: datetime,
    ) -> OnlyFeeInstruction:
        request, schedule = self._request(order, trade_id, price, quantity, timestamp, liquidity_role)
        if self._market_rules is None:
            return self._engine.instruction(
                request,
                OnlyFeeBreakdown.empty(request.currency, OnlyFeeStatus.CONFIRMED),
                created_at,
                "no_fee_configuration",
            )
        compiled = self._market_rules.compiled_rules(str(order.instrument_id), self._trading_day(timestamp))
        breakdown = self._engine.resolve_trade_fee(
            request,
            runtime_mode=compiled.identity.runtime_mode,
            market_schedule=schedule,
            broker_schedule=None,
            market_mode=OnlyFeeConfigurationMode.DEFAULT,
            broker_mode=OnlyFeeConfigurationMode.NONE,
        )
        return self._engine.instruction(request, breakdown, created_at, "market_fee_schedule")

    def _request(
        self,
        order: OnlyOrderSnapshot,
        trade_id: str,
        price: OnlyPrice,
        quantity: Decimal,
        timestamp: OnlyTimestamp,
        liquidity_role: str | None,
    ) -> tuple[OnlyFeeCalculationRequest, OnlyMarketFeeSchedule | None]:
        instrument = self._instruments[order.instrument_id]
        trading_day = self._trading_day(timestamp)
        compiled = (
            None
            if self._market_rules is None
            else self._market_rules.compiled_rules(str(order.instrument_id), trading_day)
        )
        currency = instrument.settlement_currency
        request = OnlyFeeCalculationRequest(
            str(order.runtime_id),
            str(order.cluster_id),
            str(order.account_id),
            str(order.order_id),
            trade_id,
            str(order.instrument_id),
            "UNCONFIGURED" if compiled is None else compiled.identity.profile_id,
            "0" if compiled is None else compiled.identity.profile_version,
            trading_day.value,
            order.side.value,
            order.offset.value,
            liquidity_role,
            price.value,
            quantity,
            OnlyMoney(price.value * quantity * instrument.contract_multiplier.value, currency),
            instrument.contract_multiplier.value,
            currency,
            "runtime",
            OnlyBrokerFeeReportingMode.NONE,
        )
        schedule = (
            None
            if compiled is None
            else self._market_schedules.resolve(compiled.market_fee_schedule_id, trading_day.value)
        )
        return request, schedule
