"""Immutable runtime-neutral Scenario domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.config import OnlyMarketConfig, OnlyReferenceDataConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyRuntimeMode, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


class OnlyScenarioCommandType(StrEnum):
    SUBMIT_ORDER = "SUBMIT_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"


class OnlyScenarioTriggerType(StrEnum):
    ON_BAR_SEQUENCE = "ON_BAR_SEQUENCE"
    ON_TIMESTAMP = "ON_TIMESTAMP"
    ON_TRADING_DAY_START = "ON_TRADING_DAY_START"
    AFTER_ACTION = "AFTER_ACTION"
    AFTER_ORDER_STATUS = "AFTER_ORDER_STATUS"


class OnlyScenarioFactType(StrEnum):
    ORDER = "ORDER"
    EXECUTION = "EXECUTION"
    POSITION = "POSITION"
    ACCOUNT = "ACCOUNT"
    MARKET_RULE_DECISION = "MARKET_RULE_DECISION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    FEE = "FEE"
    ACTION = "ACTION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PROFILE_TIMELINE = "PROFILE_TIMELINE"
    COMPILED_RULE = "COMPILED_RULE"


class OnlyScenarioAssertionOperator(StrEnum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    CONTAINS = "CONTAINS"
    EXISTS = "EXISTS"
    NOT_EXISTS = "NOT_EXISTS"
    COUNT_EQUALS = "COUNT_EQUALS"
    SEQUENCE_EQUALS = "SEQUENCE_EQUALS"
    DECIMAL_EQUALS = "DECIMAL_EQUALS"
    DECIMAL_APPROX = "DECIMAL_APPROX"


@dataclass(frozen=True, slots=True)
class OnlyMarketScenarioId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("scenario id must be a stable non-empty identifier")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyMarketScenarioVersion:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("scenario version cannot be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyScenarioRuntimeSpec:
    mode: OnlyRuntimeMode
    start_time: datetime
    end_time: datetime
    base_currency: str

    def __post_init__(self) -> None:
        only_require_utc(self.start_time, "scenario runtime start_time")
        only_require_utc(self.end_time, "scenario runtime end_time")
        if self.start_time >= self.end_time:
            raise ValueError("scenario runtime start_time must precede end_time")


@dataclass(frozen=True, slots=True)
class OnlyScenarioTrigger:
    trigger_type: OnlyScenarioTriggerType
    sequence: int | None = None
    timestamp: datetime | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            only_require_utc(self.timestamp, "scenario trigger timestamp")
        if self.trigger_type is OnlyScenarioTriggerType.ON_BAR_SEQUENCE and (
            self.sequence is None or self.sequence <= 0
        ):
            raise ValueError("ON_BAR_SEQUENCE requires a positive sequence")
        if self.trigger_type is OnlyScenarioTriggerType.ON_TIMESTAMP and self.timestamp is None:
            raise ValueError("ON_TIMESTAMP requires timestamp")
        if (
            self.trigger_type in {OnlyScenarioTriggerType.AFTER_ACTION, OnlyScenarioTriggerType.AFTER_ORDER_STATUS}
            and not self.reference
        ):
            raise ValueError(f"{self.trigger_type.value} requires reference")


@dataclass(frozen=True, slots=True)
class OnlyScenarioSubmitOrderCommand:
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    order_type: OnlyOrderType
    quantity: OnlyQuantity
    offset: OnlyOffset = OnlyOffset.NONE
    time_in_force: OnlyTimeInForce = OnlyTimeInForce.DAY
    price: OnlyPrice | None = None


@dataclass(frozen=True, slots=True)
class OnlyScenarioCancelOrderCommand:
    action_id: str


type OnlyScenarioCommand = OnlyScenarioSubmitOrderCommand | OnlyScenarioCancelOrderCommand


@dataclass(frozen=True, slots=True)
class OnlyScenarioAction:
    action_id: str
    trigger: OnlyScenarioTrigger
    command: OnlyScenarioCommand


@dataclass(frozen=True, slots=True)
class OnlyScenarioExpectation:
    assertion_id: str
    fact: OnlyScenarioFactType
    selector: Mapping[str, object]
    field: str | None
    operator: OnlyScenarioAssertionOperator
    expected: object = None
    tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selector", MappingProxyType(dict(self.selector)))
        if self.operator is OnlyScenarioAssertionOperator.DECIMAL_APPROX and self.tolerance is None:
            raise ValueError("DECIMAL_APPROX requires tolerance")


@dataclass(frozen=True, slots=True)
class OnlyScenarioBar:
    instrument_id: OnlyInstrumentId
    ts_event: datetime
    ts_init: datetime
    sequence: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        only_require_utc(self.ts_event, "scenario bar ts_event")
        only_require_utc(self.ts_init, "scenario bar ts_init")
        if self.ts_init < self.ts_event or self.sequence <= 0:
            raise ValueError("scenario bar causal timestamps/sequence are invalid")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("scenario bar price/volume is invalid")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("scenario bar OHLC relation is invalid")


@dataclass(frozen=True, slots=True)
class OnlyMarketScenario:
    schema_version: str
    scenario_id: OnlyMarketScenarioId
    version: OnlyMarketScenarioVersion
    description: str
    runtime: OnlyScenarioRuntimeSpec
    market: OnlyMarketConfig
    reference_data: OnlyReferenceDataConfig
    bars: tuple[OnlyScenarioBar, ...]
    actions: tuple[OnlyScenarioAction, ...]
    expectations: tuple[OnlyScenarioExpectation, ...]
    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))
