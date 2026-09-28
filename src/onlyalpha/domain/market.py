"""Immutable market data facts and fully specified bars."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyBookType,
    OnlyOrderSide,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity


def _validate_market_time(timestamp: datetime, name: str) -> None:
    only_require_utc(timestamp, name)


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
        if self.ts_init < self.ts_event:
            raise OnlyValidationError("ts_init cannot precede ts_event")
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
class OnlyReferencePriceFact(OnlyDomainModel):
    """Canonical reference-price fact; provider names terminate at adapters."""

    schema_version = 2

    fact_id: str
    instrument_id: OnlyInstrumentId
    kind: OnlyReferencePriceKind
    value: OnlyPrice
    ts_event: datetime
    ts_init: datetime
    source: str
    source_sequence: int
    data_version: str
    revision: int = 0
    provider_evidence_id: str | None = None
    source_record_hash: str | None = None

    def __post_init__(self) -> None:
        _validate_market_time(self.ts_event, "ts_event")
        _validate_market_time(self.ts_init, "ts_init")
        if self.ts_init < self.ts_event:
            raise OnlyValidationError("reference-price ts_init cannot precede ts_event")
        if (
            not self.fact_id.strip()
            or not self.source.strip()
            or not self.data_version.strip()
            or self.source_sequence < 0
            or self.revision < 0
            or self.value.value <= 0
        ):
            raise OnlyValidationError("reference-price identity/value is invalid")
        _validate_provider_lineage(self.provider_evidence_id, self.source_record_hash)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "OnlyReferencePriceFact":
        compatible = dict(payload)
        if compatible.get("schema_version") == 1:
            compatible["schema_version"] = cls.schema_version
            compatible["provider_evidence_id"] = None
            compatible["source_record_hash"] = None
        return super(OnlyReferencePriceFact, cls).from_dict(compatible)

    @property
    def stable_order(self) -> tuple[datetime, int, int, str]:
        priority = {
            OnlyReferencePriceKind.INDEX: 10,
            OnlyReferencePriceKind.MARK: 11,
            OnlyReferencePriceKind.SETTLEMENT: 12,
            OnlyReferencePriceKind.TRADE: 13,
        }[self.kind]
        return self.ts_event, priority, self.source_sequence, self.fact_id


@dataclass(frozen=True, slots=True)
class OnlyFundingRateFact(OnlyDomainModel):
    """Immutable market fact; it never mutates Account state directly."""

    schema_version = 2

    fact_id: str
    instrument_id: OnlyInstrumentId
    rate: Decimal
    funding_time: datetime
    ts_init: datetime
    source: str
    source_sequence: int
    data_version: str
    revision: int = 0
    provider_evidence_id: str | None = None
    source_record_hash: str | None = None

    def __post_init__(self) -> None:
        _validate_market_time(self.funding_time, "funding_time")
        _validate_market_time(self.ts_init, "ts_init")
        if self.ts_init < self.funding_time:
            raise OnlyValidationError("funding ts_init cannot precede funding_time")
        if (
            not self.fact_id.strip()
            or not self.source.strip()
            or not self.data_version.strip()
            or self.source_sequence < 0
            or self.revision < 0
            or not self.rate.is_finite()
        ):
            raise OnlyValidationError("funding-rate identity/value is invalid")
        _validate_provider_lineage(self.provider_evidence_id, self.source_record_hash)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "OnlyFundingRateFact":
        compatible = dict(payload)
        if compatible.get("schema_version") == 1:
            compatible["schema_version"] = cls.schema_version
            compatible["provider_evidence_id"] = None
            compatible["source_record_hash"] = None
        return super(OnlyFundingRateFact, cls).from_dict(compatible)

    @property
    def stable_order(self) -> tuple[datetime, int, int, str]:
        return self.funding_time, 20, self.source_sequence, self.fact_id


def _validate_provider_lineage(provider_evidence_id: str | None, source_record_hash: str | None) -> None:
    if (provider_evidence_id is None) != (source_record_hash is None):
        raise OnlyValidationError("provider lineage must be complete")
    if provider_evidence_id is not None and (
        not provider_evidence_id.strip()
        or source_record_hash is None
        or re.fullmatch(r"[0-9a-f]{64}", source_record_hash) is None
    ):
        raise OnlyValidationError("provider lineage is invalid")


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


class OnlyMarketReferenceKind(StrEnum):
    VENUE_REFERENCE_PRICE = "VENUE_REFERENCE_PRICE"


@dataclass(frozen=True, slots=True)
class OnlyMarketReferenceTick(OnlyTick):
    reference_kind: OnlyMarketReferenceKind
    price: OnlyPrice | None


class OnlyBarFormationKind(StrEnum):
    FIXED_DURATION = "FIXED_DURATION"
    CALENDAR_PERIOD = "CALENDAR_PERIOD"
    TICK_COUNT = "TICK_COUNT"
    VOLUME = "VOLUME"
    VALUE = "VALUE"


class OnlyBarAlignment(StrEnum):
    UTC = "UTC"
    SESSION_START = "SESSION_START"


class OnlyCalendarPeriodUnit(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


@dataclass(frozen=True, slots=True)
class OnlyFixedDurationBarFormation(OnlyDomainModel):
    window_minutes: int
    stride_minutes: int
    alignment: OnlyBarAlignment = OnlyBarAlignment.SESSION_START
    kind: OnlyBarFormationKind = OnlyBarFormationKind.FIXED_DURATION

    def __post_init__(self) -> None:
        if (
            self.kind is not OnlyBarFormationKind.FIXED_DURATION
            or type(self.window_minutes) is not int
            or type(self.stride_minutes) is not int
            or self.window_minutes < 1
            or not 1 <= self.stride_minutes <= self.window_minutes
        ):
            raise OnlyValidationError("fixed-duration Bar formation is invalid")


@dataclass(frozen=True, slots=True)
class OnlyCalendarPeriodBarFormation(OnlyDomainModel):
    unit: OnlyCalendarPeriodUnit
    count: int = 1
    alignment: OnlyBarAlignment = OnlyBarAlignment.SESSION_START
    kind: OnlyBarFormationKind = OnlyBarFormationKind.CALENDAR_PERIOD

    def __post_init__(self) -> None:
        if self.kind is not OnlyBarFormationKind.CALENDAR_PERIOD or type(self.count) is not int or self.count < 1:
            raise OnlyValidationError("calendar-period Bar formation is invalid")


@dataclass(frozen=True, slots=True)
class OnlyTickCountBarFormation(OnlyDomainModel):
    count: int
    kind: OnlyBarFormationKind = OnlyBarFormationKind.TICK_COUNT

    def __post_init__(self) -> None:
        if self.kind is not OnlyBarFormationKind.TICK_COUNT or type(self.count) is not int or self.count < 1:
            raise OnlyValidationError("tick-count Bar formation is invalid")


@dataclass(frozen=True, slots=True)
class OnlyVolumeBarFormation(OnlyDomainModel):
    quantity: Decimal
    kind: OnlyBarFormationKind = OnlyBarFormationKind.VOLUME

    def __post_init__(self) -> None:
        if self.kind is not OnlyBarFormationKind.VOLUME or self.quantity <= 0:
            raise OnlyValidationError("volume Bar formation is invalid")


@dataclass(frozen=True, slots=True)
class OnlyValueBarFormation(OnlyDomainModel):
    value: Decimal
    kind: OnlyBarFormationKind = OnlyBarFormationKind.VALUE

    def __post_init__(self) -> None:
        if self.kind is not OnlyBarFormationKind.VALUE or self.value <= 0:
            raise OnlyValidationError("value Bar formation is invalid")


type OnlyBarFormation = (
    OnlyFixedDurationBarFormation
    | OnlyCalendarPeriodBarFormation
    | OnlyTickCountBarFormation
    | OnlyVolumeBarFormation
    | OnlyValueBarFormation
)


@dataclass(frozen=True, slots=True)
class OnlyBarSemantic(OnlyDomainModel):
    schema_version = 2

    formation: OnlyBarFormation
    price_type: OnlyPriceType = OnlyPriceType.LAST
    adjustment_policy: OnlyAdjustmentType = OnlyAdjustmentType.RAW

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @property
    def is_fixed_duration(self) -> bool:
        return isinstance(self.formation, OnlyFixedDurationBarFormation)

    @property
    def window_minutes(self) -> int:
        if not isinstance(self.formation, OnlyFixedDurationBarFormation):
            raise OnlyValidationError("Bar semantic is not fixed-duration")
        return self.formation.window_minutes

    @property
    def stride_minutes(self) -> int:
        if not isinstance(self.formation, OnlyFixedDurationBarFormation):
            raise OnlyValidationError("Bar semantic is not fixed-duration")
        return self.formation.stride_minutes

    @property
    def is_aligned(self) -> bool:
        return self.is_fixed_duration and self.window_minutes == self.stride_minutes

    @classmethod
    def fixed_duration(
        cls,
        window_minutes: int,
        stride_minutes: int | None = None,
        *,
        alignment: OnlyBarAlignment = OnlyBarAlignment.SESSION_START,
        price_type: OnlyPriceType = OnlyPriceType.LAST,
        adjustment_policy: OnlyAdjustmentType = OnlyAdjustmentType.RAW,
    ) -> "OnlyBarSemantic":
        return cls(
            OnlyFixedDurationBarFormation(
                window_minutes,
                window_minutes if stride_minutes is None else stride_minutes,
                alignment,
            ),
            price_type,
            adjustment_policy,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "OnlyBarSemantic":
        if payload.get("schema_version") != cls.schema_version or not isinstance(payload.get("formation"), Mapping):
            raise OnlyValidationError("Bar semantic schema is invalid")
        formation_payload = payload["formation"]
        assert isinstance(formation_payload, Mapping)
        try:
            kind = OnlyBarFormationKind(str(formation_payload["kind"]))
            formation: OnlyBarFormation
            if kind is OnlyBarFormationKind.FIXED_DURATION:
                formation = OnlyFixedDurationBarFormation.from_dict(formation_payload)
            elif kind is OnlyBarFormationKind.CALENDAR_PERIOD:
                formation = OnlyCalendarPeriodBarFormation.from_dict(formation_payload)
            elif kind is OnlyBarFormationKind.TICK_COUNT:
                formation = OnlyTickCountBarFormation.from_dict(formation_payload)
            elif kind is OnlyBarFormationKind.VOLUME:
                formation = OnlyVolumeBarFormation.from_dict(formation_payload)
            else:
                formation = OnlyValueBarFormation.from_dict(formation_payload)
            semantic = cls(
                formation,
                OnlyPriceType(str(payload["price_type"])),
                OnlyAdjustmentType(str(payload["adjustment_policy"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyValidationError("Bar semantic is invalid") from exc
        if semantic.to_dict() != dict(payload):
            raise OnlyValidationError("Bar semantic is invalid")
        return semantic


@dataclass(frozen=True, slots=True)
class OnlyBarType(OnlyDomainModel):
    schema_version = 2

    instrument_id: OnlyInstrumentId
    semantic: OnlyBarSemantic


@dataclass(frozen=True, slots=True)
class OnlyTradeSemantic:
    """Canonical unaggregated trade input semantic."""

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "kind": "TRADE"}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OnlyTradeSemantic":
        if dict(value) != cls().to_dict():
            raise OnlyValidationError("Trade semantic is invalid")
        return cls()


@dataclass(frozen=True, slots=True)
class OnlyTradeInputType:
    instrument_id: OnlyInstrumentId
    semantic: OnlyTradeSemantic = OnlyTradeSemantic()

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "instrument_id": str(self.instrument_id), "semantic": self.semantic.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OnlyTradeInputType":
        if value.get("schema_version") != 1 or not isinstance(value.get("semantic"), Mapping):
            raise OnlyValidationError("Trade input is invalid")
        semantic = value["semantic"]
        assert isinstance(semantic, Mapping)
        result = cls(OnlyInstrumentId.parse(str(value["instrument_id"])), OnlyTradeSemantic.from_dict(semantic))
        if result.to_dict() != dict(value):
            raise OnlyValidationError("Trade input is invalid")
        return result


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
        if self.ts_init < self.ts_event:
            raise OnlyValidationError("bar ts_init cannot precede ts_event")
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
        if self.adjustment_type is not self.bar_type.semantic.adjustment_policy:
            raise OnlyValidationError("bar adjustment does not match Bar semantic")

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
