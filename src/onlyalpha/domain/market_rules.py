"""Composable, effective-dated market rules kept separate from instruments."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate, only_decimal


@dataclass(frozen=True, slots=True)
class OnlyValidationResult(OnlyDomainModel):
    violations: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.violations


@dataclass(frozen=True, slots=True)
class OnlyLotSizeRule(OnlyDomainModel):
    buy_increment: Decimal
    sell_increment: Decimal

    def __post_init__(self) -> None:
        for name in ("buy_increment", "sell_increment"):
            value = only_decimal(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)

    def validates(self, side: OnlyOrderSide, quantity: OnlyQuantity) -> bool:
        increment = self.buy_increment if side is OnlyOrderSide.BUY else self.sell_increment
        return quantity.value % increment == 0


@dataclass(frozen=True, slots=True)
class OnlySettlementRule(OnlyDomainModel):
    settlement_days: int
    allow_same_day_sell: bool = True
    allowed_offsets: tuple[OnlyOffset, ...] = tuple(OnlyOffset)

    def __post_init__(self) -> None:
        if self.settlement_days < 0:
            raise ValueError("settlement_days cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyPriceLimitRule(OnlyDomainModel):
    lower: OnlyPrice | None = None
    upper: OnlyPrice | None = None

    def validates(self, price: OnlyPrice) -> bool:
        return (self.lower is None or price.value >= self.lower.value) and (
            self.upper is None or price.value <= self.upper.value
        )


@dataclass(frozen=True, slots=True)
class OnlyPriceLadder(OnlyDomainModel):
    """Ordered upper bounds and their tick increments; None is the final open bound."""

    steps: tuple[tuple[Decimal | None, Decimal], ...]

    def increment_for(self, price: OnlyPrice) -> Decimal:
        for upper, increment in self.steps:
            if upper is None or price.value <= upper:
                return increment
        raise ValueError("price ladder requires an open final bound")


@dataclass(frozen=True, slots=True)
class OnlyTickScheme(OnlyDomainModel):
    ladder: OnlyPriceLadder

    def validates(self, price: OnlyPrice) -> bool:
        return price.value % self.ladder.increment_for(price) == 0


@dataclass(frozen=True, slots=True)
class OnlyFeeSchedule(OnlyDomainModel):
    schedule_id: str
    maker_rate: OnlyRate
    taker_rate: OnlyRate
    minimum_fee: OnlyMoney
    effective_from: datetime
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        only_require_utc(self.effective_from, "fee schedule effective_from")
        if self.effective_to is not None:
            only_require_utc(self.effective_to, "fee schedule effective_to")
            if self.effective_to <= self.effective_from:
                raise ValueError("fee schedule effective interval must be increasing")

    def calculate(self, notional: OnlyMoney, liquidity: OnlyLiquiditySide) -> OnlyMoney:
        if notional.currency != self.minimum_fee.currency:
            raise ValueError("fee notional currency mismatch")
        rate = self.maker_rate if liquidity is OnlyLiquiditySide.MAKER else self.taker_rate
        raw = notional.amount * rate.value
        amount = max(raw, self.minimum_fee.amount)
        quantum = Decimal(1).scaleb(-notional.currency.precision)
        return OnlyMoney(amount.quantize(quantum, rounding=ROUND_DOWN), notional.currency)

    def is_effective_at(self, timestamp: datetime) -> bool:
        only_require_utc(timestamp, "fee schedule query")
        return timestamp >= self.effective_from and (self.effective_to is None or timestamp < self.effective_to)


@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleCatalog(OnlyDomainModel):
    schedules: tuple[OnlyFeeSchedule, ...]

    def resolve(self, schedule_id: str, as_of: datetime) -> OnlyFeeSchedule:
        matches = [item for item in self.schedules if item.schedule_id == schedule_id and item.is_effective_at(as_of)]
        if len(matches) != 1:
            raise ValueError(f"expected one effective fee schedule for {schedule_id}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class OnlyTradingRule(OnlyDomainModel):
    minimum_notional: OnlyMoney | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketRule(OnlyDomainModel):
    rule_id: str
    lot_size_rule: OnlyLotSizeRule
    settlement_rule: OnlySettlementRule
    trading_rule: OnlyTradingRule = OnlyTradingRule()
    price_limit_rule: OnlyPriceLimitRule | None = None
    tick_scheme: OnlyTickScheme | None = None
    fee_schedule: OnlyFeeSchedule | None = None
    calendar: OnlyTradingCalendar | None = None

    def validate_order(
        self,
        instrument: OnlyInstrument,
        request: OnlyOrderRequest,
        price: OnlyPrice | None = None,
    ) -> OnlyValidationResult:
        violations: list[str] = []
        target_price = price or request.limit_price
        if request.instrument_id != instrument.instrument_id:
            violations.append("instrument_id_mismatch")
        if not instrument.is_valid_quantity(request.quantity):
            violations.append("instrument_quantity")
        if not self.lot_size_rule.validates(request.side, request.quantity):
            violations.append("lot_size")
        if request.offset not in self.settlement_rule.allowed_offsets:
            violations.append("offset")
        if target_price is not None:
            if not instrument.is_valid_price(target_price):
                violations.append("instrument_price")
            if self.price_limit_rule and not self.price_limit_rule.validates(target_price):
                violations.append("price_limit")
            if self.tick_scheme and not self.tick_scheme.validates(target_price):
                violations.append("price_ladder")
            minimum = self.trading_rule.minimum_notional
            if minimum and target_price.value * request.quantity.value < minimum.amount:
                violations.append("minimum_notional")
        return OnlyValidationResult(tuple(violations))
