"""Runtime-agnostic configuration value models and JSON normalization helpers."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import yaml  # type: ignore[import-untyped]

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId

type OnlyJsonValue = str | int | float | bool | None | list[OnlyJsonValue] | dict[str, OnlyJsonValue]
type OnlyJsonMapping = Mapping[str, OnlyJsonValue]


class OnlyConfigError(ValueError):
    pass


class OnlyUniverseType(StrEnum):
    STATIC = "STATIC"
    INDEX_CONSTITUENTS = "INDEX_CONSTITUENTS"
    QUERY = "QUERY"
    FILE = "FILE"
    REFERENCE_DATA = "REFERENCE_DATA"
    DYNAMIC = "DYNAMIC"


class OnlySubscriptionRole(StrEnum):
    PRIMARY = "PRIMARY"
    AUXILIARY = "AUXILIARY"


@dataclass(frozen=True, slots=True)
class OnlyReferenceDataConfig:
    calendars: tuple[OnlyTradingCalendar, ...]
    instruments: tuple[OnlyInstrument, ...]

    @property
    def calendar_by_id(self) -> Mapping[OnlyCalendarId, OnlyTradingCalendar]:
        return MappingProxyType({x.calendar_id: x for x in self.calendars})

    @property
    def instrument_by_id(self) -> Mapping[OnlyInstrumentId, OnlyInstrument]:
        return MappingProxyType({x.instrument_id: x for x in self.instruments})


@dataclass(frozen=True, slots=True)
class OnlyUniverseConfig:
    universe_id: str
    universe_type: OnlyUniverseType
    instrument_ids: tuple[OnlyInstrumentId, ...] = ()
    provider: OnlyJsonMapping = field(default_factory=lambda: MappingProxyType({}))
    extensions: OnlyJsonMapping = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.universe_type is OnlyUniverseType.STATIC and not self.instrument_ids:
            raise OnlyConfigError(f"static universe {self.universe_id!r} must contain instruments")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceCoverageConfig:
    universe_ids: tuple[str, ...] = ()
    instrument_ids: tuple[OnlyInstrumentId, ...] = ()

    def __post_init__(self) -> None:
        if not self.universe_ids and not self.instrument_ids:
            raise OnlyConfigError("data source coverage requires universe_ids or instrument_ids")


@dataclass(frozen=True, slots=True)
class OnlyDataSourceRuntimeConfig:
    source_id: OnlyMarketDataSourceId
    source_type: str
    data_version: OnlyDataVersion
    coverage: OnlyDataSourceCoverageConfig
    batch_size: int = 1024
    extensions: OnlyJsonMapping = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class OnlyAccountRuntimeConfig:
    account_id: OnlyAccountId
    gateway_id: OnlyBrokerGatewayId
    initial_cash: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyBrokerRuntimeConfig:
    gateway_id: OnlyBrokerGatewayId
    gateway_type: str
    extensions: OnlyJsonMapping = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class OnlyBarSpecificationConfig:
    step: int
    aggregation: OnlyBarAggregation
    price_type: OnlyPriceType
    source: OnlyAggregationSource

    def to_bar_type(self, instrument_id: OnlyInstrumentId) -> OnlyBarType:
        return OnlyBarType(
            instrument_id,
            OnlyBarSpecification(self.step, self.aggregation, self.price_type),
            self.source,
        )


@dataclass(frozen=True, slots=True)
class OnlyInstrumentBarSubscriptionConfig:
    instrument_id: OnlyInstrumentId
    bar_specification: OnlyBarSpecificationConfig
    role: OnlySubscriptionRole


@dataclass(frozen=True, slots=True)
class OnlyUniverseBarSubscriptionConfig:
    universe_id: str
    bar_specification: OnlyBarSpecificationConfig
    role: OnlySubscriptionRole


@dataclass(frozen=True, slots=True)
class OnlyStrategySubscriptionConfig:
    instrument_bars: tuple[OnlyInstrumentBarSubscriptionConfig, ...] = ()
    universe_bars: tuple[OnlyUniverseBarSubscriptionConfig, ...] = ()

    def __post_init__(self) -> None:
        if not self.instrument_bars and not self.universe_bars:
            raise OnlyConfigError("strategy subscriptions cannot be empty")
        primary_count = sum(x.role is OnlySubscriptionRole.PRIMARY for x in self.instrument_bars)
        primary_count += sum(x.role is OnlySubscriptionRole.PRIMARY for x in self.universe_bars)
        if primary_count != 1:
            raise OnlyConfigError("each strategy must declare exactly one PRIMARY subscription")


@dataclass(frozen=True, slots=True)
class OnlyStrategyImportConfig:
    strategy_path: str
    config_path: str
    extensions: OnlyJsonMapping

    def __post_init__(self) -> None:
        _validate_import_path(self.strategy_path, "strategy_path")
        _validate_import_path(self.config_path, "config_path")


@dataclass(frozen=True, slots=True)
class OnlyIndicatorSpecConfig:
    indicator_id: OnlyIndicatorId
    indicator_type: OnlyIndicatorTypeId
    parameters: OnlyJsonMapping


@dataclass(frozen=True, slots=True)
class OnlyFactorImportConfig:
    factor_id: OnlyFactorId
    factor_type: str
    factor_path: str
    config_path: str
    subscriptions: OnlyStrategySubscriptionConfig
    indicators: tuple[OnlyIndicatorSpecConfig, ...]
    dependencies: tuple[OnlyFactorId, ...]
    required: bool
    extensions: OnlyJsonMapping

    def __post_init__(self) -> None:
        _validate_import_path(self.factor_path, "factor_path")
        _validate_import_path(self.config_path, "config_path")


@dataclass(frozen=True, slots=True)
class OnlyClusterImportConfig:
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    enabled: bool
    strategy: OnlyStrategyImportConfig
    factors: tuple[OnlyFactorImportConfig, ...]
    risk_profile_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def _load_document(path: Path) -> OnlyJsonMapping:
    if not path.is_file():
        raise OnlyConfigError(f"config not found: {path}")
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            raise OnlyConfigError("config extension must be .json, .yaml or .yml")
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OnlyConfigError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise OnlyConfigError("config root must be mapping")
    return _normalize_mapping(raw, "$")


def _normalize_mapping(value: Mapping[object, object], path: str) -> OnlyJsonMapping:
    result: dict[str, OnlyJsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise OnlyConfigError(f"{path} contains non-string key")
        result[key] = _normalize_value(item, f"{path}.{key}")
    return MappingProxyType(result)


def _normalize_value(value: object, path: str) -> OnlyJsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not Decimal(str(value)).is_finite():
            raise OnlyConfigError(f"{path} cannot be NaN/Infinity")
        return value
    if isinstance(value, Mapping):
        return dict(_normalize_mapping(value, path))
    if isinstance(value, list):
        return [_normalize_value(x, f"{path}[{i}]") for i, x in enumerate(value)]
    if isinstance(value, (date, datetime, time)):
        raise OnlyConfigError(f"{path} was implicitly parsed as {type(value).__name__}; quote date/time values")
    raise OnlyConfigError(f"{path} contains unsupported type {type(value).__name__}")


def _instrument_id(value: str, path: str) -> OnlyInstrumentId:
    if "." not in value:
        raise OnlyConfigError(f"{path} must use SYMBOL.VENUE")
    symbol, venue = value.rsplit(".", 1)
    if not symbol or not venue:
        raise OnlyConfigError(f"{path} must use SYMBOL.VENUE")
    return OnlyInstrumentId(OnlySymbol(symbol), OnlyVenueId(venue))


def _validate_import_path(value: str, path: str) -> None:
    if value.count(":") != 1:
        raise OnlyConfigError(f"{path} must use python.module:ClassName")
    module, class_name = value.split(":", 1)
    if not module or not class_name or class_name.startswith("_"):
        raise OnlyConfigError(f"{path} must reference a public python class")
