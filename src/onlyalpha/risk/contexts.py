"""Restricted immutable contexts supplied to Risk Rules and state updates."""

from dataclasses import dataclass

from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.risk.ports import (
    OnlyAccountRiskView,
    OnlyClusterPermissionView,
    OnlyInstrumentRiskView,
    OnlyMarketRuleRiskView,
    OnlyOrderRiskView,
    OnlyPositionRiskView,
    OnlyRiskReservationView,
    OnlyStrategyLedgerRiskViewPort,
)


@dataclass(frozen=True, slots=True)
class OnlyRiskEvaluationContext:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    clock: OnlyClockView
    instruments: OnlyInstrumentRiskView
    market_rules: OnlyMarketRuleRiskView
    trading_calendar: OnlyTradingCalendar
    orders: OnlyOrderRiskView
    reservations: OnlyRiskReservationView
    permissions: OnlyClusterPermissionView
    account_risk: OnlyAccountRiskView
    position_risk: OnlyPositionRiskView
    supported_order_types: frozenset[OnlyOrderType]
    profile_bound: bool
    kill_switch_active: bool
    market_data: OnlyMarketDataSnapshot | None = None
    strategy_ledger: OnlyStrategyLedgerRiskViewPort | None = None


@dataclass(frozen=True, slots=True)
class OnlyRiskStateUpdateContext:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    market_data: OnlyMarketDataSnapshot | None = None
