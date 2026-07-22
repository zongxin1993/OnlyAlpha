"""Runtime composition helper for one authoritative fee calculation path."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

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
from onlyalpha.fee.schedules import (
    OnlyBrokerFeeSchedule,
    OnlyBrokerFeeScheduleRegistry,
    OnlyMarketFeeSchedule,
    OnlyMarketFeeScheduleRegistry,
)
from onlyalpha.market.runtime_rules import OnlyTradeInstructionPort


@dataclass(frozen=True, slots=True)
class OnlyFeeResolverConfig:
    market_mode: OnlyFeeConfigurationMode = OnlyFeeConfigurationMode.DEFAULT
    market_schedule_id: str | None = None
    broker_mode: OnlyFeeConfigurationMode = OnlyFeeConfigurationMode.NONE
    broker_schedule_id: str | None = None
    broker_id: str = "runtime"
    broker_reporting_mode: OnlyBrokerFeeReportingMode = OnlyBrokerFeeReportingMode.NONE

    def __post_init__(self) -> None:
        if self.market_mode is OnlyFeeConfigurationMode.MODEL and self.market_schedule_id is None:
            raise ValueError("market MODEL fee configuration requires a schedule")
        if self.broker_mode is OnlyFeeConfigurationMode.MODEL and self.broker_schedule_id is None:
            raise ValueError("broker MODEL fee configuration requires a schedule")
        if self.market_mode is OnlyFeeConfigurationMode.REPORTED:
            raise ValueError("market fee configuration cannot use REPORTED mode")
        if not self.broker_id:
            raise ValueError("fee resolver broker_id cannot be empty")


class OnlyFeeResolver:
    """Resolves estimates and fills with the same schedules and market identity."""

    def __init__(
        self,
        engine: OnlyFeeEngine,
        market_schedules: OnlyMarketFeeScheduleRegistry,
        broker_schedules: OnlyBrokerFeeScheduleRegistry,
        market_rules: OnlyTradeInstructionPort | None,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay],
        config: OnlyFeeResolverConfig | None = None,
    ) -> None:
        self._engine = engine
        self._market_schedules = market_schedules
        self._broker_schedules = broker_schedules
        self._market_rules = market_rules
        self._instruments = instruments
        self._trading_day = trading_day
        self._config = config or OnlyFeeResolverConfig()

    def estimate_order(self, order: OnlyOrderSnapshot, price: OnlyPrice, timestamp: OnlyTimestamp) -> OnlyFeeEstimate:
        request, market_schedule, broker_schedule = self._request(
            order,
            trade_id=f"estimate:{order.order_id}",
            price=price,
            quantity=order.quantity.value,
            timestamp=timestamp,
            liquidity_role=None,
        )
        return self._engine.estimate(
            request,
            market_schedule=market_schedule,
            broker_schedule=broker_schedule,
            market_mode=self._market_mode(market_schedule),
            broker_mode=self._broker_mode(broker_schedule),
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
        reported_fee: OnlyMoney | None = None,
        reporting_mode: OnlyBrokerFeeReportingMode | None = None,
    ) -> OnlyFeeInstruction:
        request, market_schedule, broker_schedule = self._request(
            order,
            trade_id,
            price,
            quantity,
            timestamp,
            liquidity_role,
            reported_fee,
            reporting_mode,
        )
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
            market_schedule=market_schedule,
            broker_schedule=broker_schedule,
            market_mode=self._market_mode(market_schedule),
            broker_mode=self._broker_mode(broker_schedule),
        )
        return self._engine.instruction(request, breakdown, created_at, "runtime_fee_resolver")

    def _request(
        self,
        order: OnlyOrderSnapshot,
        trade_id: str,
        price: OnlyPrice,
        quantity: Decimal,
        timestamp: OnlyTimestamp,
        liquidity_role: str | None,
        reported_fee: OnlyMoney | None = None,
        reporting_mode: OnlyBrokerFeeReportingMode | None = None,
    ) -> tuple[OnlyFeeCalculationRequest, OnlyMarketFeeSchedule | None, OnlyBrokerFeeSchedule | None]:
        instrument = self._instruments[order.instrument_id]
        trading_day = self._trading_day(timestamp)
        compiled = (
            None
            if self._market_rules is None
            else self._market_rules.compiled_rules(str(order.instrument_id), trading_day)
        )
        currency = instrument.settlement_currency
        quantum = Decimal(1).scaleb(-currency.precision)
        notional = OnlyMoney(
            (price.value * quantity * instrument.contract_multiplier.value).quantize(quantum, ROUND_HALF_EVEN),
            currency,
        )
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
            notional,
            instrument.contract_multiplier.value,
            currency,
            self._config.broker_id,
            reporting_mode or self._config.broker_reporting_mode,
            reported_fee,
        )
        market_schedule_id = self._config.market_schedule_id
        if self._config.market_mode is OnlyFeeConfigurationMode.DEFAULT and compiled is not None:
            market_schedule_id = compiled.market_fee_schedule_id
        market_schedule = (
            None
            if self._config.market_mode is OnlyFeeConfigurationMode.NONE
            or (self._config.market_mode is OnlyFeeConfigurationMode.DEFAULT and compiled is None)
            else self._market_schedules.resolve(self._require_schedule(market_schedule_id, "market"), trading_day.value)
        )
        broker_schedule = (
            self._broker_schedules.resolve(
                self._require_schedule(self._config.broker_schedule_id, "broker"), trading_day.value
            )
            if self._config.broker_mode is OnlyFeeConfigurationMode.MODEL
            else None
        )
        return request, market_schedule, broker_schedule

    def _market_mode(self, schedule: OnlyMarketFeeSchedule | None) -> OnlyFeeConfigurationMode:
        if self._config.market_mode is OnlyFeeConfigurationMode.NONE:
            return OnlyFeeConfigurationMode.NONE
        if self._config.market_mode is OnlyFeeConfigurationMode.DEFAULT and self._market_rules is None:
            return OnlyFeeConfigurationMode.NONE
        if schedule is None:
            raise ValueError("market fee configuration requires a resolved schedule")
        return OnlyFeeConfigurationMode.MODEL

    def _broker_mode(self, schedule: OnlyBrokerFeeSchedule | None) -> OnlyFeeConfigurationMode:
        if self._config.broker_mode is OnlyFeeConfigurationMode.DEFAULT:
            raise ValueError("broker DEFAULT fee configuration requires an explicit Runtime default")
        if self._config.broker_mode is OnlyFeeConfigurationMode.MODEL and schedule is None:
            raise ValueError("broker fee configuration requires a resolved schedule")
        return self._config.broker_mode

    @staticmethod
    def _require_schedule(schedule_id: str | None, authority: str) -> str:
        if schedule_id is None:
            raise ValueError(f"{authority} fee configuration requires a schedule")
        return schedule_id
