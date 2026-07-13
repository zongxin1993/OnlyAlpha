"""Versioned, market-neutral instrument specifications."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyAssetClass,
    OnlyContractType,
    OnlyExerciseStyle,
    OnlyInstrumentType,
    OnlyMarketType,
    OnlyOptionType,
    OnlySecurityStatus,
    OnlySettlementType,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyInstrumentId,
    OnlyRawSymbol,
    OnlySessionProfileId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimeZone, only_require_utc
from onlyalpha.domain.value import (
    OnlyCurrency,
    OnlyMoney,
    OnlyMultiplier,
    OnlyPrice,
    OnlyQuantity,
    OnlyRate,
)


def _validate_aware(timestamp: datetime | None, field_name: str) -> None:
    if timestamp is not None:
        only_require_utc(timestamp, field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyInstrument(OnlyDomainModel):
    """Immutable instrument definition valid for a bounded time interval."""

    instrument_id: OnlyInstrumentId
    raw_symbol: OnlyRawSymbol
    asset_class: OnlyAssetClass
    instrument_type: OnlyInstrumentType
    market_type: OnlyMarketType
    quote_currency: OnlyCurrency
    settlement_currency: OnlyCurrency
    price_precision: int
    quantity_precision: int
    tick_size: OnlyPrice
    step_size: OnlyQuantity
    contract_multiplier: OnlyMultiplier = OnlyMultiplier(Decimal("1"), 0)
    base_currency: OnlyCurrency | None = None
    margin_currency: OnlyCurrency | None = None
    minimum_quantity: OnlyQuantity | None = None
    maximum_quantity: OnlyQuantity | None = None
    minimum_notional: OnlyMoney | None = None
    maximum_notional: OnlyMoney | None = None
    minimum_price: OnlyPrice | None = None
    maximum_price: OnlyPrice | None = None
    lot_size: OnlyQuantity | None = None
    instrument_version: int = 1
    activation_time: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    timezone: str = "UTC"
    trading_calendar_id: OnlyCalendarId | None = None
    session_profile_id: OnlySessionProfileId | None = None
    status: OnlySecurityStatus = OnlySecurityStatus.ACTIVE

    @property
    def venue(self) -> OnlyVenueId:
        return self.instrument_id.venue

    @property
    def price_increment(self) -> OnlyPrice:
        return self.tick_size

    @property
    def quantity_increment(self) -> OnlyQuantity:
        return self.step_size

    @property
    def version(self) -> int:
        return self.instrument_version

    def __post_init__(self) -> None:
        if isinstance(self.trading_calendar_id, str):
            object.__setattr__(self, "trading_calendar_id", OnlyCalendarId(self.trading_calendar_id))
        OnlyTimeZone(self.timezone)
        if self.price_precision != self.tick_size.precision:
            raise OnlyValidationError("tick_size precision must equal instrument price_precision")
        if self.quantity_precision != self.step_size.precision:
            raise OnlyValidationError("step_size precision must equal instrument quantity_precision")
        if self.tick_size.value <= 0 or self.step_size.value <= 0:
            raise OnlyValidationError("tick_size and step_size must be positive")
        if self.instrument_version < 1:
            raise OnlyValidationError("instrument_version must be positive")
        _validate_aware(self.effective_from, "effective_from")
        _validate_aware(self.effective_to, "effective_to")
        _validate_aware(self.activation_time, "activation_time")
        if self.effective_from and self.effective_to and self.effective_from >= self.effective_to:
            raise OnlyValidationError("instrument effective interval must be increasing")
        for quantity in (self.minimum_quantity, self.maximum_quantity, self.lot_size):
            if quantity is not None and quantity.precision != self.quantity_precision:
                raise OnlyValidationError("instrument quantity constraint precision mismatch")
        if self.minimum_quantity and self.maximum_quantity:
            if self.minimum_quantity.value > self.maximum_quantity.value:
                raise OnlyValidationError("minimum_quantity exceeds maximum_quantity")
        if self.minimum_notional and self.maximum_notional:
            if self.minimum_notional.currency != self.maximum_notional.currency:
                raise OnlyValidationError("notional limits must use one currency")
            if self.minimum_notional.amount > self.maximum_notional.amount:
                raise OnlyValidationError("minimum_notional exceeds maximum_notional")
        for price in (self.minimum_price, self.maximum_price):
            if price is not None and price.precision != self.price_precision:
                raise OnlyValidationError("instrument price constraint precision mismatch")
        if self.minimum_price and self.maximum_price:
            if self.minimum_price.value > self.maximum_price.value:
                raise OnlyValidationError("minimum_price exceeds maximum_price")

    def validates_price(self, price: OnlyPrice) -> bool:
        if price.precision != self.price_precision or price.value % self.tick_size.value != 0:
            return False
        if self.minimum_price and price.value < self.minimum_price.value:
            return False
        return not self.maximum_price or price.value <= self.maximum_price.value

    def is_valid_price(self, price: OnlyPrice) -> bool:
        """Stable public alias used at order-validation boundaries."""
        return self.validates_price(price)

    def validates_quantity(self, quantity: OnlyQuantity) -> bool:
        if quantity.precision != self.quantity_precision or quantity.value % self.step_size.value != 0:
            return False
        if self.minimum_quantity and quantity.value < self.minimum_quantity.value:
            return False
        return not self.maximum_quantity or quantity.value <= self.maximum_quantity.value

    def is_valid_quantity(self, quantity: OnlyQuantity) -> bool:
        return self.validates_quantity(quantity)

    def quantize_price(self, price: OnlyPrice, *, rounding: str) -> OnlyPrice:
        try:
            units = (price.value / self.tick_size.value).to_integral_value(rounding=rounding)
        except (InvalidOperation, ValueError) as exc:
            raise OnlyValidationError("invalid explicit price rounding mode") from exc
        return OnlyPrice(units * self.tick_size.value, self.price_precision)

    def quantize_quantity(self, quantity: OnlyQuantity, *, rounding: str) -> OnlyQuantity:
        try:
            units = (quantity.value / self.step_size.value).to_integral_value(rounding=rounding)
        except (InvalidOperation, ValueError) as exc:
            raise OnlyValidationError("invalid explicit quantity rounding mode") from exc
        return OnlyQuantity(units * self.step_size.value, self.quantity_precision)

    def is_effective_at(self, timestamp: datetime) -> bool:
        _validate_aware(timestamp, "timestamp")
        return (self.effective_from is None or timestamp >= self.effective_from) and (
            self.effective_to is None or timestamp < self.effective_to
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyEquity(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.EQUITY, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.EQUITY, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyETF(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.ETF, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.FUND, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFund(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.FUND, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.FUND, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFuture(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.FUTURE, init=False)
    underlying: OnlyInstrumentId
    expiration_time: datetime
    last_trade_time: datetime
    settlement_type: OnlySettlementType
    contract_type: OnlyContractType = OnlyContractType.LINEAR
    initial_margin_rate: OnlyRate | None = None
    maintenance_margin_rate: OnlyRate | None = None

    def __post_init__(self) -> None:
        super(OnlyFuture, self).__post_init__()
        _validate_aware(self.expiration_time, "expiration_time")
        _validate_aware(self.last_trade_time, "last_trade_time")
        if self.last_trade_time > self.expiration_time:
            raise OnlyValidationError("last_trade_time cannot follow expiration_time")
        if self.margin_currency is None:
            raise OnlyValidationError("future requires margin_currency")
        _validate_contract_currencies(self, self.contract_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyOption(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.OPTION, init=False)
    underlying: OnlyInstrumentId
    strike_price: OnlyPrice
    expiration_time: datetime
    option_type: OnlyOptionType
    exercise_style: OnlyExerciseStyle
    settlement_type: OnlySettlementType

    def __post_init__(self) -> None:
        super(OnlyOption, self).__post_init__()
        _validate_aware(self.expiration_time, "expiration_time")
        if self.strike_price.value <= 0:
            raise OnlyValidationError("option strike_price must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyIndex(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.INDEX, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.INDEX, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommodity(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.COMMODITY, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.COMMODITY, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFxPair(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.FX_PAIR, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.FX, init=False)

    def __post_init__(self) -> None:
        super(OnlyFxPair, self).__post_init__()
        if self.base_currency is None or self.base_currency == self.quote_currency:
            raise OnlyValidationError("FX pair requires distinct base and quote currencies")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCryptoSpot(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.CRYPTO_SPOT, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.CRYPTOCURRENCY, init=False)

    def __post_init__(self) -> None:
        super(OnlyCryptoSpot, self).__post_init__()
        if self.base_currency is None or self.base_currency == self.quote_currency:
            raise OnlyValidationError("crypto spot requires distinct base and quote currencies")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCryptoFuture(OnlyFuture):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.CRYPTO_FUTURE, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.CRYPTOCURRENCY, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCryptoPerpetual(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.CRYPTO_PERPETUAL, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.CRYPTOCURRENCY, init=False)
    contract_type: OnlyContractType = OnlyContractType.LINEAR

    def __post_init__(self) -> None:
        super(OnlyCryptoPerpetual, self).__post_init__()
        if self.base_currency is None or self.margin_currency is None:
            raise OnlyValidationError("crypto perpetual requires base and margin currencies")
        _validate_contract_currencies(self, self.contract_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlySyntheticInstrument(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.SYNTHETIC, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.SYNTHETIC, init=False)
    expression: str

    def __post_init__(self) -> None:
        super(OnlySyntheticInstrument, self).__post_init__()
        if not self.expression.strip():
            raise OnlyValidationError("synthetic instrument expression is required")


def _validate_contract_currencies(instrument: OnlyInstrument, contract_type: OnlyContractType) -> None:
    if contract_type is OnlyContractType.INVERSE:
        if instrument.base_currency is None or instrument.settlement_currency != instrument.base_currency:
            raise OnlyValidationError("inverse contract must settle in base currency")
    if contract_type is OnlyContractType.QUANTO and instrument.settlement_currency in {
        instrument.base_currency,
        instrument.quote_currency,
    }:
        raise OnlyValidationError("quanto contract must settle in a third currency")
