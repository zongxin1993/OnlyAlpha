"""Market-neutral rule models used by simulation and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.settlement.models import (
    OnlyCompiledSettlementPolicy,
    OnlySettlementSchedule,
    OnlySettlementScheduleRequest,
)


class OnlySettlementTiming(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    T_PLUS_ZERO = "T_PLUS_ZERO"
    T_PLUS_ONE = "T_PLUS_ONE"
    T_PLUS_N = "T_PLUS_N"
    SESSION_END = "SESSION_END"
    NEXT_TRADING_DAY = "NEXT_TRADING_DAY"
    FUTURES_DAILY_MARK_TO_MARK = "FUTURES_DAILY_MARK_TO_MARK"


class OnlyMarketPositionMode(StrEnum):
    LONG_ONLY = "LONG_ONLY"
    NETTING = "NETTING"
    HEDGING = "HEDGING"


class OnlyPositionEffect(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"
    REDUCE_ONLY = "REDUCE_ONLY"
    AUTO = "AUTO"


class OnlyShortSellingMode(StrEnum):
    DISABLED = "DISABLED"
    ENABLED_WITH_BORROW = "ENABLED_WITH_BORROW"
    ENABLED_UNRESTRICTED = "ENABLED_UNRESTRICTED"


class OnlyTradingPhase(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    OPENING_AUCTION = "OPENING_AUCTION"
    CONTINUOUS = "CONTINUOUS"
    MIDDAY_BREAK = "MIDDAY_BREAK"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"


class OnlyPriceBandRoundingMode(StrEnum):
    HALF_UP_TO_TICK = "HALF_UP_TO_TICK"


class OnlyMarketRuleEvaluationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class OnlySettlementRule:
    timing: OnlySettlementTiming
    lag: int = 0

    def __post_init__(self) -> None:
        if self.lag < 0:
            raise ValueError("settlement lag cannot be negative")
        if self.timing is OnlySettlementTiming.T_PLUS_N and self.lag < 1:
            raise ValueError("T_PLUS_N requires a positive lag")


class OnlyTradingDayAdvancer(Protocol):
    def __call__(self, day: OnlyTradingDay, lag: int) -> OnlyTradingDay: ...


@dataclass(frozen=True, slots=True)
class OnlySettlementModel:
    model_id: str
    asset_settlement: OnlySettlementRule
    cash_settlement: OnlySettlementRule
    asset_availability: OnlySettlementRule
    cash_availability: OnlySettlementRule

    def compile(self) -> OnlyCompiledSettlementPolicy:
        return OnlyCompiledSettlementPolicy(
            self.model_id,
            0,
            self._lag(self.asset_availability),
            0,
            self._lag(self.cash_availability),
            self._lag(self.cash_settlement),
            max(self._lag(self.asset_settlement), self._lag(self.cash_settlement)),
        )

    def schedule(
        self, request: OnlySettlementScheduleRequest, advance: OnlyTradingDayAdvancer
    ) -> OnlySettlementSchedule:
        policy = self.compile()
        day = request.trading_day
        return OnlySettlementSchedule(
            advance(day, policy.asset_booking_lag),
            advance(day, policy.asset_trade_availability_lag),
            advance(day, policy.cash_booking_lag),
            advance(day, policy.cash_trade_availability_lag),
            advance(day, policy.cash_withdrawal_lag),
            advance(day, policy.legal_settlement_lag),
            policy.policy_id,
        )

    @staticmethod
    def _lag(rule: OnlySettlementRule) -> int:
        if rule.timing in {OnlySettlementTiming.IMMEDIATE, OnlySettlementTiming.T_PLUS_ZERO}:
            return 0
        if rule.timing in {OnlySettlementTiming.T_PLUS_ONE, OnlySettlementTiming.NEXT_TRADING_DAY}:
            return 1
        return rule.lag


@dataclass(frozen=True, slots=True)
class OnlyPositionAccountingModel:
    mode: OnlyMarketPositionMode
    allow_flip: bool = False


@dataclass(frozen=True, slots=True)
class OnlyShortSellingRule:
    mode: OnlyShortSellingMode


@dataclass(frozen=True, slots=True)
class OnlyMarginRequirement:
    notional: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal


@dataclass(frozen=True, slots=True)
class OnlyMarginState:
    collateral: Decimal
    used_margin: Decimal
    maintenance_margin: Decimal

    @property
    def available_margin(self) -> Decimal:
        return self.collateral - self.used_margin

    @property
    def margin_ratio(self) -> Decimal | None:
        return None if self.maintenance_margin == 0 else self.collateral / self.maintenance_margin


@dataclass(frozen=True, slots=True)
class OnlyMarginModel:
    model_id: str
    initial_rate: Decimal
    maintenance_rate: Decimal

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.maintenance_rate <= self.initial_rate <= Decimal(1):
            raise ValueError("margin rates must satisfy 0 <= maintenance <= initial <= 1")

    def requirement(self, price: Decimal, quantity: Decimal, multiplier: Decimal) -> OnlyMarginRequirement:
        notional = price * quantity * multiplier
        return OnlyMarginRequirement(notional, notional * self.initial_rate, notional * self.maintenance_rate)

    def can_open(self, state: OnlyMarginState, requirement: OnlyMarginRequirement) -> bool:
        return state.available_margin >= requirement.initial_margin


@dataclass(frozen=True, slots=True)
class OnlyTradingSessionDefinition:
    name: str
    opens_at: time
    closes_at: time
    phase: OnlyTradingPhase
    trading_day_offset: int = 0
    allows_orders: bool = True

    @property
    def crosses_midnight(self) -> bool:
        return self.opens_at > self.closes_at

    def contains(self, timestamp: datetime) -> bool:
        wall = timestamp.timetz().replace(tzinfo=None)
        if self.opens_at == self.closes_at:
            return True
        if self.crosses_midnight:
            return wall >= self.opens_at or wall < self.closes_at
        return self.opens_at <= wall < self.closes_at


@dataclass(frozen=True, slots=True)
class OnlyTradingSessionState:
    phase: OnlyTradingPhase
    trading_day: date
    session_name: str | None
    allows_orders: bool


@dataclass(frozen=True, slots=True)
class OnlyTradingSessionModel:
    model_id: str
    timezone: str
    sessions: tuple[OnlyTradingSessionDefinition, ...]
    continuous_24x7: bool = False

    def state_at(self, local_timestamp: datetime) -> OnlyTradingSessionState:
        if local_timestamp.tzinfo is None:
            raise ValueError("session timestamp must be timezone-aware")
        for session in self.sessions:
            if session.contains(local_timestamp):
                anchor = local_timestamp.date()
                if session.crosses_midnight and local_timestamp.time().replace(tzinfo=None) < session.closes_at:
                    anchor -= timedelta(days=1)
                return OnlyTradingSessionState(
                    session.phase,
                    anchor + timedelta(days=session.trading_day_offset),
                    session.name,
                    session.allows_orders,
                )
        return OnlyTradingSessionState(OnlyTradingPhase.CLOSED, local_timestamp.date(), None, False)


@dataclass(frozen=True, slots=True)
class OnlyCompiledPriceBandPolicy:
    regime_id: str
    tick_size: Decimal
    previous_close: Decimal | None
    daily_limit_rate: Decimal | None
    lower_limit: Decimal | None
    upper_limit: Decimal | None
    rounding_mode: OnlyPriceBandRoundingMode


@dataclass(frozen=True, slots=True)
class OnlyCompiledQuantityPolicy:
    minimum_buy_quantity: Decimal
    buy_quantity_increment: Decimal
    minimum_sell_quantity: Decimal
    sell_quantity_increment: Decimal
    odd_lot_liquidation_allowed: bool
    maximum_limit_order_quantity: Decimal | None
    allow_fractional: bool


@dataclass(frozen=True, slots=True)
class OnlyMarketRuleEvaluation:
    rule_code: str
    status: OnlyMarketRuleEvaluationStatus
    reason_code: str | None
    inputs: tuple[tuple[str, str], ...] = ()


def only_next_calendar_day(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
    """Test/default advancer; production callers supply their versioned trading calendar."""
    return OnlyTradingDay(day.value + timedelta(days=lag))
