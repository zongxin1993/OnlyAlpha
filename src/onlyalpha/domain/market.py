"""Immutable market data facts and fully specified bars."""

from dataclasses import dataclass
from datetime import date, datetime

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyBookType,
    OnlyOrderSide,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity


def _validate_market_time(timestamp: datetime, name: str) -> None:
    if timestamp.tzinfo is None:
        raise OnlyValidationError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class OnlyTick(OnlyDomainModel):
    instrument_id: OnlyInstrumentId
    ts_event: datetime
    ts_init: datetime
    sequence: int
    source: str

    def __post_init__(self) -> None:
        _validate_market_time(self.ts_event, "ts_event")
        _validate_market_time(self.ts_init, "ts_init")
        if self.sequence < 0 or not self.source.strip():
            raise OnlyValidationError("tick sequence and source are required")


@dataclass(frozen=True, slots=True)
class OnlyTradeTick(OnlyTick):
    price: OnlyPrice
    quantity: OnlyQuantity
    aggressor_side: OnlyOrderSide | None
    trade_id: OnlyTradeId

    def __post_init__(self) -> None:
        super(OnlyTradeTick, self).__post_init__()
        if self.quantity.value <= 0:
            raise OnlyValidationError("trade tick quantity must be positive")


@dataclass(frozen=True, slots=True)
class OnlyQuoteTick(OnlyTick):
    bid_price: OnlyPrice
    bid_quantity: OnlyQuantity
    ask_price: OnlyPrice
    ask_quantity: OnlyQuantity

    def __post_init__(self) -> None:
        super(OnlyQuoteTick, self).__post_init__()
        if self.bid_price.precision != self.ask_price.precision:
            raise OnlyValidationError("quote prices must share precision")
        if self.bid_quantity.value < 0 or self.ask_quantity.value < 0:
            raise OnlyValidationError("quote quantities cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyBarSpecification(OnlyDomainModel):
    step: int
    aggregation: OnlyBarAggregation
    price_type: OnlyPriceType

    def __post_init__(self) -> None:
        if self.step <= 0:
            raise OnlyValidationError("bar step must be positive")


@dataclass(frozen=True, slots=True)
class OnlyBarType(OnlyDomainModel):
    instrument_id: OnlyInstrumentId
    specification: OnlyBarSpecification
    aggregation_source: OnlyAggregationSource


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBar(OnlyDomainModel):
    """OHLCV fact for the half-open interval [bar_start, bar_end)."""

    bar_type: OnlyBarType
    open: OnlyPrice
    high: OnlyPrice
    low: OnlyPrice
    close: OnlyPrice
    volume: OnlyQuantity
    quote_volume: OnlyQuantity | None
    turnover: OnlyMoney | None
    trade_count: int | None
    open_interest: OnlyQuantity | None
    bar_start: datetime
    bar_end: datetime
    ts_event: datetime
    ts_init: datetime
    is_closed: bool
    revision: int
    adjustment_type: OnlyAdjustmentType
    trading_day: date
    session_type: OnlySessionType

    @property
    def instrument_id(self) -> OnlyInstrumentId:
        return self.bar_type.instrument_id

    def __post_init__(self) -> None:
        for name in ("bar_start", "bar_end", "ts_event", "ts_init"):
            _validate_market_time(getattr(self, name), name)
        if self.bar_start >= self.bar_end:
            raise OnlyValidationError("bar interval must be increasing")
        if self.ts_event < self.bar_start or self.revision < 0:
            raise OnlyValidationError("bar event time and revision are invalid")
        precisions = {self.open.precision, self.high.precision, self.low.precision, self.close.precision}
        if len(precisions) != 1:
            raise OnlyValidationError("bar prices must share one precision")
        if self.high.value < max(self.open.value, self.close.value, self.low.value):
            raise OnlyValidationError("bar high is below another OHLC value")
        if self.low.value > min(self.open.value, self.close.value, self.high.value):
            raise OnlyValidationError("bar low is above another OHLC value")
        if self.trade_count is not None and self.trade_count < 0:
            raise OnlyValidationError("bar trade_count cannot be negative")
        if not self.is_closed and self.revision != 0:
            raise OnlyValidationError("an updating bar cannot carry a revision")

    def contains(self, timestamp: datetime) -> bool:
        _validate_market_time(timestamp, "timestamp")
        return self.bar_start <= timestamp < self.bar_end


@dataclass(frozen=True, slots=True)
class OnlyOrderBookLevel(OnlyDomainModel):
    price: OnlyPrice
    quantity: OnlyQuantity
    order_count: int | None = None

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise OnlyValidationError("order book level quantity must be positive")
        if self.order_count is not None and self.order_count < 0:
            raise OnlyValidationError("order_count cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyOrderBook(OnlyDomainModel):
    instrument_id: OnlyInstrumentId
    book_type: OnlyBookType
    bids: tuple[OnlyOrderBookLevel, ...]
    asks: tuple[OnlyOrderBookLevel, ...]
    sequence: int
    event_time: datetime

    def __post_init__(self) -> None:
        _validate_market_time(self.event_time, "event_time")
        if self.sequence < 0:
            raise OnlyValidationError("order book sequence cannot be negative")
        if any(left.price.value <= right.price.value for left, right in zip(self.bids, self.bids[1:], strict=False)):
            raise OnlyValidationError("bid levels must be strictly descending")
        if any(left.price.value >= right.price.value for left, right in zip(self.asks, self.asks[1:], strict=False)):
            raise OnlyValidationError("ask levels must be strictly ascending")

    @property
    def is_crossed(self) -> bool:
        return bool(self.bids and self.asks and self.bids[0].price.value >= self.asks[0].price.value)
