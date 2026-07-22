"""Market-neutral rule models used by simulation and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from onlyalpha.domain.enums import OnlyAssetClass, OnlyOrderSide
from onlyalpha.domain.time import OnlyTradingDay, only_require_utc


class OnlyMarketProfileId(StrEnum):
    CN_A_SHARE_CASH = "CN_A_SHARE_CASH"
    HK_EQUITY_CASH = "HK_EQUITY_CASH"
    US_EQUITY_CASH = "US_EQUITY_CASH"
    CN_FUTURES = "CN_FUTURES"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_PERPETUAL = "CRYPTO_PERPETUAL"
    CRYPTO_DELIVERY_FUTURE = "CRYPTO_DELIVERY_FUTURE"
    FX_SPOT = "FX_SPOT"
    GENERIC_T0_CASH = "GENERIC_T0_CASH"
    GENERIC_MARGIN_FUTURES = "GENERIC_MARGIN_FUTURES"
    GENERIC_24X7_CRYPTO_SPOT = "GENERIC_24X7_CRYPTO_SPOT"


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


class OnlyLiquidityModelType(StrEnum):
    UNLIMITED = "UNLIMITED"
    BAR_VOLUME_PARTICIPATION = "BAR_VOLUME_PARTICIPATION"
    TICK = "TICK"
    ORDER_BOOK = "ORDER_BOOK"
    EXCHANGE_REPORTED = "EXCHANGE_REPORTED"


class OnlySlippageModelType(StrEnum):
    NONE = "NONE"
    FIXED_TICKS = "FIXED_TICKS"
    BASIS_POINTS = "BASIS_POINTS"
    VOLUME_IMPACT = "VOLUME_IMPACT"


class OnlyMatchingModelType(StrEnum):
    NEXT_BAR_OPEN = "NEXT_BAR_OPEN"
    NEXT_BAR_CLOSE = "NEXT_BAR_CLOSE"
    BAR_TOUCH = "BAR_TOUCH"
    TICK = "TICK"
    ORDER_BOOK = "ORDER_BOOK"
    EXCHANGE_NATIVE = "EXCHANGE_NATIVE"


class OnlyFeeBasis(StrEnum):
    NOTIONAL = "NOTIONAL"
    QUANTITY = "QUANTITY"
    CONTRACT = "CONTRACT"
    FIXED = "FIXED"


@dataclass(frozen=True, slots=True)
class OnlySettlementRule:
    timing: OnlySettlementTiming
    lag: int = 0

    def __post_init__(self) -> None:
        if self.lag < 0:
            raise ValueError("settlement lag cannot be negative")
        if self.timing is OnlySettlementTiming.T_PLUS_N and self.lag < 1:
            raise ValueError("T_PLUS_N requires a positive lag")


@dataclass(frozen=True, slots=True)
class OnlySettlementContext:
    execution_id: str
    account_id: str
    instrument_id: str
    side: OnlyOrderSide
    quantity: Decimal
    cash_amount: Decimal
    trade_time: datetime
    trading_day: OnlyTradingDay

    def __post_init__(self) -> None:
        only_require_utc(self.trade_time, "settlement trade_time")
        if self.quantity <= 0 or self.cash_amount < 0:
            raise ValueError("settlement quantity must be positive and cash non-negative")


@dataclass(frozen=True, slots=True)
class OnlySettlementInstruction:
    instruction_id: str
    execution_id: str
    asset_quantity: Decimal
    cash_amount: Decimal
    trade_time: datetime
    asset_available_day: OnlyTradingDay
    cash_available_day: OnlyTradingDay
    legal_settlement_day: OnlyTradingDay
    model_id: str


class OnlyTradingDayAdvancer(Protocol):
    def __call__(self, day: OnlyTradingDay, lag: int) -> OnlyTradingDay: ...


@dataclass(frozen=True, slots=True)
class OnlySettlementModel:
    model_id: str
    asset_settlement: OnlySettlementRule
    cash_settlement: OnlySettlementRule
    asset_availability: OnlySettlementRule
    cash_availability: OnlySettlementRule

    def on_execution(
        self, context: OnlySettlementContext, advance: OnlyTradingDayAdvancer
    ) -> OnlySettlementInstruction:
        asset_available = advance(context.trading_day, self._lag(self.asset_availability))
        cash_available = advance(context.trading_day, self._lag(self.cash_availability))
        legal_lag = max(self._lag(self.asset_settlement), self._lag(self.cash_settlement))
        legal_day = advance(context.trading_day, legal_lag)
        payload = f"{self.model_id}|{context.execution_id}|{context.trade_time.isoformat()}"
        return OnlySettlementInstruction(
            instruction_id=hashlib.sha256(payload.encode()).hexdigest(),
            execution_id=context.execution_id,
            asset_quantity=context.quantity,
            cash_amount=context.cash_amount,
            trade_time=context.trade_time,
            asset_available_day=asset_available,
            cash_available_day=cash_available,
            legal_settlement_day=legal_day,
            model_id=self.model_id,
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
class OnlyInstrumentReferenceSnapshot:
    instrument_id: str
    asset_class: OnlyAssetClass
    venue: str
    market_profile_id: OnlyMarketProfileId
    currency: str
    effective_from: datetime
    effective_to: datetime | None
    source: str
    source_version: str
    content_fingerprint: str
    base_currency: str | None = None
    quote_currency: str | None = None
    settlement_currency: str | None = None
    status: str = "ACTIVE"
    price_precision: int = 2
    quantity_precision: int = 0
    tick_size: Decimal = Decimal("0.01")
    quantity_step: Decimal = Decimal(1)
    minimum_quantity: Decimal | None = None
    maximum_quantity: Decimal | None = None
    minimum_notional: Decimal | None = None
    maximum_notional: Decimal | None = None
    lot_size: Decimal | None = None
    contract_multiplier: Decimal = Decimal(1)
    board: str | None = None
    st_status: bool = False
    suspended: bool = False
    trading_calendar_id: str | None = None

    def __post_init__(self) -> None:
        only_require_utc(self.effective_from, "reference effective_from")
        if self.effective_to is not None:
            only_require_utc(self.effective_to, "reference effective_to")


@dataclass(frozen=True, slots=True)
class OnlyPriceRule:
    tick_size: Decimal
    daily_limit_rate: Decimal | None = None

    def price_limits(self, previous_close: Decimal | None) -> tuple[Decimal, Decimal] | None:
        if previous_close is None or self.daily_limit_rate is None:
            return None
        return previous_close * (1 - self.daily_limit_rate), previous_close * (1 + self.daily_limit_rate)


@dataclass(frozen=True, slots=True)
class OnlyQuantityRule:
    allow_fractional: bool
    buy_lot_required: bool = False
    allow_odd_lot_liquidation: bool = False

    def validate(
        self,
        reference: OnlyInstrumentReferenceSnapshot,
        side: OnlyOrderSide,
        quantity: Decimal,
        price: Decimal | None = None,
        available_quantity: Decimal | None = None,
    ) -> str | None:
        if quantity <= 0 or quantity % reference.quantity_step != 0:
            return "INVALID_QUANTITY_STEP"
        if not self.allow_fractional and quantity != quantity.to_integral_value():
            return "FRACTIONAL_QUANTITY_DISABLED"
        if reference.minimum_quantity is not None and quantity < reference.minimum_quantity:
            return "BELOW_MINIMUM_QUANTITY"
        if price is not None and reference.minimum_notional is not None:
            if price * quantity * reference.contract_multiplier < reference.minimum_notional:
                return "BELOW_MINIMUM_NOTIONAL"
        lot = reference.lot_size
        if side is OnlyOrderSide.BUY and self.buy_lot_required and lot is not None and quantity % lot != 0:
            return "BUY_LOT_REQUIRED"
        if side is OnlyOrderSide.SELL and lot is not None and quantity % lot != 0:
            if not self.allow_odd_lot_liquidation or available_quantity != quantity:
                return "ODD_LOT_ONLY_FOR_LIQUIDATION"
        return None


@dataclass(frozen=True, slots=True)
class OnlyLiquidityModel:
    model_type: OnlyLiquidityModelType
    maximum_participation_rate: Decimal = Decimal(1)

    def capacity(self, normalized_bar_volume: Decimal | None, consumed: Decimal = Decimal(0)) -> Decimal | None:
        if self.model_type is OnlyLiquidityModelType.UNLIMITED:
            return None
        if normalized_bar_volume is None:
            raise ValueError("bar participation requires normalized volume")
        return max(normalized_bar_volume * self.maximum_participation_rate - consumed, Decimal(0))


@dataclass(frozen=True, slots=True)
class OnlySlippageModel:
    model_type: OnlySlippageModelType
    value: Decimal = Decimal(0)

    def apply(self, reference_price: Decimal, side: OnlyOrderSide, tick_size: Decimal) -> Decimal:
        direction = Decimal(1) if side is OnlyOrderSide.BUY else Decimal(-1)
        if self.model_type is OnlySlippageModelType.NONE:
            return reference_price
        if self.model_type is OnlySlippageModelType.FIXED_TICKS:
            return reference_price + direction * self.value * tick_size
        if self.model_type is OnlySlippageModelType.BASIS_POINTS:
            return reference_price * (1 + direction * self.value / Decimal(10000))
        raise NotImplementedError("volume impact is an extension boundary")


@dataclass(frozen=True, slots=True)
class OnlyMatchingModel:
    model_type: OnlyMatchingModelType


@dataclass(frozen=True, slots=True)
class OnlyMarketProfile:
    profile_id: OnlyMarketProfileId
    market: str
    venue: str | None
    asset_classes: tuple[OnlyAssetClass, ...]
    session_model: OnlyTradingSessionModel
    settlement_model: OnlySettlementModel
    position_model: OnlyPositionAccountingModel
    short_selling_rule: OnlyShortSellingRule
    margin_model: OnlyMarginModel | None
    price_rule: OnlyPriceRule
    quantity_rule: OnlyQuantityRule
    market_fee_schedule_id: str
    liquidity_model: OnlyLiquidityModel
    slippage_model: OnlySlippageModel
    matching_model: OnlyMatchingModel
    effective_from: date
    effective_to: date | None
    version: str
    source: str
    strict: bool = True

    @property
    def content_fingerprint(self) -> str:
        def normalize(value: object) -> object:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, (date, datetime, time)):
                return value.isoformat()
            if isinstance(value, StrEnum):
                return value.value
            if isinstance(value, dict):
                return {str(k): normalize(v) for k, v in sorted(value.items(), key=lambda i: str(i[0]))}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            return value

        payload = json.dumps(normalize(asdict(self)), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


OnlyEffectiveMarketRules = OnlyMarketProfile


class OnlyMarketProfileResolver:
    def __init__(self, profiles: tuple[OnlyMarketProfile, ...]) -> None:
        self._profiles = profiles

    def resolve(self, profile_id: OnlyMarketProfileId, effective_on: date) -> OnlyEffectiveMarketRules:
        matches = tuple(
            profile
            for profile in self._profiles
            if profile.profile_id is profile_id
            and profile.effective_from <= effective_on
            and (profile.effective_to is None or effective_on < profile.effective_to)
        )
        if len(matches) != 1:
            raise ValueError(f"expected one effective {profile_id} profile on {effective_on}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class OnlyMarketRuleDecision:
    rule_type: str
    accepted: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketValidationContext:
    reference: OnlyInstrumentReferenceSnapshot
    profile: OnlyEffectiveMarketRules
    side: OnlyOrderSide
    quantity: Decimal
    price: Decimal
    local_time: datetime
    available_quantity: Decimal = Decimal(0)
    previous_close: Decimal | None = None


class OnlyMarketOrderValidator:
    """Deterministic pre-trade validation without future market data."""

    def validate(self, context: OnlyMarketValidationContext) -> tuple[OnlyMarketRuleDecision, ...]:
        decisions: list[OnlyMarketRuleDecision] = []
        session = context.profile.session_model.state_at(context.local_time)
        decisions.append(
            OnlyMarketRuleDecision(
                "SESSION", session.allows_orders, None if session.allows_orders else f"PHASE_{session.phase}"
            )
        )
        tradable = context.reference.status == "ACTIVE" and not context.reference.suspended
        decisions.append(
            OnlyMarketRuleDecision("TRADABILITY", tradable, None if tradable else "INSTRUMENT_NOT_TRADABLE")
        )
        quantity_reason = context.profile.quantity_rule.validate(
            context.reference,
            context.side,
            context.quantity,
            context.price,
            context.available_quantity,
        )
        decisions.append(OnlyMarketRuleDecision("QUANTITY", quantity_reason is None, quantity_reason))
        if (
            context.side is OnlyOrderSide.SELL
            and context.profile.position_model.mode is OnlyMarketPositionMode.LONG_ONLY
        ):
            position_ok = context.quantity <= context.available_quantity
            decisions.append(
                OnlyMarketRuleDecision(
                    "POSITION", position_ok, None if position_ok else "INSUFFICIENT_AVAILABLE_QUANTITY"
                )
            )
        price_ok = context.price > 0 and context.price % context.reference.tick_size == 0
        reason = None if price_ok else "INVALID_PRICE_TICK"
        limits = context.profile.price_rule.price_limits(context.previous_close)
        if price_ok and limits is not None and not limits[0] <= context.price <= limits[1]:
            price_ok, reason = False, "OUTSIDE_DAILY_PRICE_LIMIT"
        decisions.append(OnlyMarketRuleDecision("PRICE", price_ok, reason))
        return tuple(decisions)


def only_next_calendar_day(day: OnlyTradingDay, lag: int) -> OnlyTradingDay:
    """Test/default advancer; production callers supply their versioned trading calendar."""
    return OnlyTradingDay(day.value + timedelta(days=lag))
