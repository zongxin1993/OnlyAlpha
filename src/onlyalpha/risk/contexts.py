"""Restricted immutable contexts supplied to Risk Rules and state updates."""

from dataclasses import dataclass

from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.risk.ports import (
    OnlyAccountRiskView,
    OnlyClusterPermissionView,
    OnlyInstrumentRiskView,
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
    position_side: OnlyPositionSide = OnlyPositionSide.LONG
    position_effect: OnlyPositionEffect = OnlyPositionEffect.AUTO
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING
    order_planning_price: OnlyPrice | None = None
    market_snapshot_fingerprint: str | None = None
    market_update_id: str | None = None
    execution_profile_fingerprint: str | None = None


def only_risk_planning_details(context: OnlyRiskEvaluationContext) -> dict[str, str]:
    """Return transient causal evidence for a price-dependent Risk decision."""

    details: dict[str, str] = {}
    if context.order_planning_price is not None:
        details["planning_price"] = str(context.order_planning_price.value)
    if context.market_snapshot_fingerprint is not None:
        details["market_snapshot_fingerprint"] = context.market_snapshot_fingerprint
    if context.market_update_id is not None:
        details["market_update_id"] = context.market_update_id
    if context.execution_profile_fingerprint is not None:
        details["execution_profile_fingerprint"] = context.execution_profile_fingerprint
    return details


@dataclass(frozen=True, slots=True)
class OnlyRiskStateUpdateContext:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    market_data: OnlyMarketDataSnapshot | None = None
