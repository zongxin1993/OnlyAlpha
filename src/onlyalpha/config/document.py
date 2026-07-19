"""OnlyAlpha runtime-agnostic run document parser.

本模块只解析通用运行配置，不导入具体 Runtime、数据源、Broker、策略或指标实现。
策略扩展参数由 strategy.config_path 对应的具体配置类解析。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.config.models import (
    OnlyAccountRuntimeConfig,
    OnlyBarSpecificationConfig,
    OnlyBrokerRuntimeConfig,
    OnlyClusterImportConfig,
    OnlyConfigError,
    OnlyDataSourceCoverageConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyFactorImportConfig,
    OnlyIndicatorSpecConfig,
    OnlyInstrumentBarSubscriptionConfig,
    OnlyJsonMapping,
    OnlyJsonValue,
    OnlyReferenceDataConfig,
    OnlyStrategyImportConfig,
    OnlyStrategySubscriptionConfig,
    OnlySubscriptionRole,
    OnlyUniverseBarSubscriptionConfig,
    OnlyUniverseConfig,
    OnlyUniverseType,
    _instrument_id,
    _normalize_mapping,
)
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyMarketType,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyRawSymbol,
    OnlyRuntimeId,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity, OnlyETF, OnlyInstrument
from onlyalpha.domain.time import OnlyTimeZone, only_require_utc
from onlyalpha.domain.value import (
    OnlyCurrency,
    OnlyMoney,
    OnlyMultiplier,
    OnlyPrice,
    OnlyQuantity,
)
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId


class OnlyClusterConfigError(OnlyConfigError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyRuntimeConfig:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    runtime_type: str
    start_time: datetime | None
    end_time: datetime | None
    base_currency: OnlyCurrency
    extensions: OnlyJsonMapping

    def __post_init__(self) -> None:
        if self.runtime_type not in {"BACKTEST", "PAPER", "LIVE", "SHADOW", "RESEARCH"}:
            raise OnlyClusterConfigError(f"unsupported runtime.type value: {self.runtime_type}")
        if self.start_time is not None:
            only_require_utc(self.start_time, "runtime.start_time")
        if self.end_time is not None:
            only_require_utc(self.end_time, "runtime.end_time")
        if self.start_time is not None and self.end_time is not None and self.start_time >= self.end_time:
            raise OnlyClusterConfigError("runtime.start_time must be before end_time")


@dataclass(frozen=True, slots=True)
class OnlyOutputConfig:
    formats: tuple[str, ...] = ("JSON",)
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class OnlyRuntimeAssemblyPlan:
    """Internal Runtime assembly DTO.

    This is not a user configuration document. Product configuration is
    represented by ``OnlyClusterRunConfig`` and the Engine creates this plan
    only after Runtime compatibility planning.
    """

    schema_version: str
    runtime: OnlyRuntimeConfig
    reference_data: OnlyReferenceDataConfig
    universes: tuple[OnlyUniverseConfig, ...]
    data_sources: tuple[OnlyDataSourceRuntimeConfig, ...]
    accounts: tuple[OnlyAccountRuntimeConfig, ...]
    brokers: tuple[OnlyBrokerRuntimeConfig, ...]
    clusters: tuple[OnlyClusterImportConfig, ...]
    output: OnlyOutputConfig
    source_path: Path
    normalized_payload: OnlyJsonMapping

    @property
    def engine_id(self) -> OnlyEngineId:
        return self.runtime.engine_id

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.runtime.runtime_id

    @property
    def start_time(self) -> datetime | None:
        return self.runtime.start_time

    @property
    def end_time(self) -> datetime | None:
        return self.runtime.end_time

    @property
    def base_currency(self) -> OnlyCurrency:
        return self.runtime.base_currency

    def __post_init__(self) -> None:
        self._validate_references()

    def _validate_references(self) -> None:
        instruments = {str(x.instrument_id) for x in self.reference_data.instruments}
        calendars = {str(x.calendar_id) for x in self.reference_data.calendars}
        universes = {x.universe_id for x in self.universes}
        brokers = {str(x.gateway_id) for x in self.brokers}
        accounts = {str(x.account_id) for x in self.accounts}

        if len(instruments) != len(self.reference_data.instruments):
            raise OnlyClusterConfigError("duplicate instrument_id")
        if len(calendars) != len(self.reference_data.calendars):
            raise OnlyClusterConfigError("duplicate calendar_id")
        if len(universes) != len(self.universes):
            raise OnlyClusterConfigError("duplicate universe_id")
        if len(brokers) != len(self.brokers):
            raise OnlyClusterConfigError("duplicate gateway_id")
        if len(accounts) != len(self.accounts):
            raise OnlyClusterConfigError("duplicate account_id")

        for instrument in self.reference_data.instruments:
            if str(instrument.trading_calendar_id) not in calendars:
                raise OnlyClusterConfigError(
                    f"{instrument.instrument_id} references unknown calendar {instrument.trading_calendar_id}"
                )
        for universe in self.universes:
            for instrument_id in universe.instrument_ids:
                if str(instrument_id) not in instruments:
                    raise OnlyClusterConfigError(f"{universe.universe_id} references unknown {instrument_id}")
        for source in self.data_sources:
            for universe_id in source.coverage.universe_ids:
                if universe_id not in universes:
                    raise OnlyClusterConfigError(f"{source.source_id} references unknown universe {universe_id}")
            for instrument_id in source.coverage.instrument_ids:
                if str(instrument_id) not in instruments:
                    raise OnlyClusterConfigError(f"{source.source_id} references unknown {instrument_id}")
        for account in self.accounts:
            if str(account.gateway_id) not in brokers:
                raise OnlyClusterConfigError(f"{account.account_id} references unknown gateway {account.gateway_id}")
            if account.initial_cash.currency != self.base_currency:
                raise OnlyClusterConfigError(f"{account.account_id} currency differs from runtime base currency")
        seen_clusters: set[str] = set()
        for cluster in self.clusters:
            cluster_id = str(cluster.cluster_id)
            if cluster_id in seen_clusters:
                raise OnlyClusterConfigError(f"duplicate cluster_id {cluster_id}")
            seen_clusters.add(cluster_id)
            if str(cluster.account_id) not in accounts:
                raise OnlyClusterConfigError(f"{cluster_id} references unknown account {cluster.account_id}")
            factor_ids = {factor.factor_id for factor in cluster.factors}
            if len(factor_ids) != len(cluster.factors):
                raise OnlyClusterConfigError(f"{cluster_id} has duplicate factor_id")
            for factor in cluster.factors:
                if not set(factor.dependencies) <= factor_ids:
                    raise OnlyClusterConfigError(f"{factor.factor_id} references unknown Factor dependency")
                for instrument_subscription in factor.subscriptions.instrument_bars:
                    if str(instrument_subscription.instrument_id) not in instruments:
                        raise OnlyClusterConfigError(
                            f"{cluster_id} references unknown {instrument_subscription.instrument_id}"
                        )
                for universe_subscription in factor.subscriptions.universe_bars:
                    if universe_subscription.universe_id not in universes:
                        raise OnlyClusterConfigError(
                            f"{cluster_id} references unknown universe {universe_subscription.universe_id}"
                        )


class _OnlyClusterDocumentParser:
    def __init__(self, source: Path, root: OnlyJsonMapping) -> None:
        self.source = source
        self.root = root

    def _runtime(self, raw: OnlyJsonMapping, engine: OnlyJsonMapping) -> OnlyRuntimeConfig:
        currency = OnlyCurrency(
            self._str(raw.get("base_currency", "CNY"), "$.runtime.base_currency"),
            2,
            OnlyCurrencyType.FIAT,
        )
        return OnlyRuntimeConfig(
            OnlyEngineId(self._str(engine.get("engine_id", raw.get("engine_id", "onlyalpha")), "$.engine.engine_id")),
            OnlyRuntimeId(self._str(raw.get("runtime_id"), "$.runtime.runtime_id")),
            self._str(raw.get("type", raw.get("runtime_type", "BACKTEST")), "$.runtime.type").upper(),
            self._optional_utc(raw.get("start_time"), "$.runtime.start_time"),
            self._optional_utc(raw.get("end_time"), "$.runtime.end_time"),
            currency,
            self._map(raw.get("extensions", {}), "$.runtime.extensions"),
        )

    def _reference(self, raw: OnlyJsonMapping, currency: OnlyCurrency) -> OnlyReferenceDataConfig:
        calendars = tuple(
            self._calendar(self._map(x, f"$.reference_data.calendars[{i}]"), f"$.reference_data.calendars[{i}]")
            for i, x in enumerate(self._list(raw.get("calendars"), "$.reference_data.calendars"))
        )
        instruments = tuple(
            self._instrument(
                self._map(x, f"$.reference_data.instruments[{i}]"),
                f"$.reference_data.instruments[{i}]",
                currency,
            )
            for i, x in enumerate(self._list(raw.get("instruments"), "$.reference_data.instruments"))
        )
        return OnlyReferenceDataConfig(calendars, instruments)

    def _calendar(self, raw: OnlyJsonMapping, path: str) -> OnlyTradingCalendar:
        sessions = tuple(
            OnlyTradingSession(
                self._str(item.get("name"), f"{p}.name"),
                time.fromisoformat(self._str(item.get("opens_at"), f"{p}.opens_at")),
                time.fromisoformat(self._str(item.get("closes_at"), f"{p}.closes_at")),
                OnlySessionType(self._str(item.get("session_type", "CONTINUOUS"), f"{p}.session_type")),
            )
            for i, value in enumerate(self._list(raw.get("sessions"), f"{path}.sessions"))
            for p in (f"{path}.sessions[{i}]",)
            for item in (self._map(value, p),)
        )
        return OnlyTradingCalendar(
            OnlyCalendarId(self._str(raw.get("calendar_id"), f"{path}.calendar_id")),
            OnlyVenueId(self._str(raw.get("venue"), f"{path}.venue")),
            OnlyTimeZone(self._str(raw.get("timezone"), f"{path}.timezone")),
            sessions,
            holidays=tuple(
                date.fromisoformat(self._str(x, f"{path}.holidays[{i}]"))
                for i, x in enumerate(self._list(raw.get("holidays", []), f"{path}.holidays"))
            ),
        )

    def _instrument(self, raw: OnlyJsonMapping, path: str, base_currency: OnlyCurrency) -> OnlyInstrument:
        asset_class = self._str(raw.get("asset_class", "ETF"), f"{path}.asset_class")
        instrument_type: type[OnlyETF] | type[OnlyEquity]
        if asset_class == "ETF":
            instrument_type = OnlyETF
        elif asset_class == "EQUITY":
            instrument_type = OnlyEquity
        else:
            raise OnlyClusterConfigError(f"{path}.asset_class={asset_class!r} is not yet supported")
        instrument_id = _instrument_id(
            self._str(raw.get("instrument_id"), f"{path}.instrument_id"),
            f"{path}.instrument_id",
        )
        symbol, venue = str(instrument_id).rsplit(".", 1)
        price_precision = self._int(raw.get("price_precision", 2), f"{path}.price_precision", 0)
        quantity_precision = self._int(raw.get("quantity_precision", 0), f"{path}.quantity_precision", 0)
        lot = self._decimal(raw.get("lot_size"), f"{path}.lot_size", positive=True)
        return instrument_type(
            instrument_id=instrument_id,
            raw_symbol=OnlyRawSymbol(symbol),
            market_type=OnlyMarketType.CASH,
            quote_currency=base_currency,
            settlement_currency=base_currency,
            price_precision=price_precision,
            quantity_precision=quantity_precision,
            tick_size=OnlyPrice(
                self._decimal(raw.get("price_increment"), f"{path}.price_increment", positive=True),
                price_precision,
            ),
            step_size=OnlyQuantity(
                self._decimal(raw.get("quantity_increment"), f"{path}.quantity_increment", positive=True),
                quantity_precision,
            ),
            lot_size=OnlyQuantity(lot, quantity_precision),
            minimum_quantity=OnlyQuantity(
                self._decimal(raw.get("minimum_quantity", str(lot)), f"{path}.minimum_quantity", positive=True),
                quantity_precision,
            ),
            maximum_quantity=OnlyQuantity(
                self._decimal(raw.get("maximum_quantity", "100000000"), f"{path}.maximum_quantity", positive=True),
                quantity_precision,
            ),
            contract_multiplier=OnlyMultiplier(
                self._decimal(raw.get("contract_multiplier", "1"), f"{path}.contract_multiplier", positive=True),
                0,
            ),
            trading_calendar_id=OnlyCalendarId(
                self._str(raw.get("trading_calendar_id"), f"{path}.trading_calendar_id")
            ),
            timezone=OnlyTimeZone(self._str(raw.get("timezone"), f"{path}.timezone")).name,
        )

    def _universes(self, values: list[OnlyJsonValue]) -> tuple[OnlyUniverseConfig, ...]:
        result = []
        for i, value in enumerate(values):
            p = f"$.universes[{i}]"
            raw = self._map(value, p)
            result.append(
                OnlyUniverseConfig(
                    self._str(raw.get("universe_id"), f"{p}.universe_id"),
                    OnlyUniverseType(self._str(raw.get("type", "STATIC"), f"{p}.type")),
                    tuple(
                        _instrument_id(self._str(x, f"{p}.instruments[{j}]"), f"{p}.instruments[{j}]")
                        for j, x in enumerate(self._list(raw.get("instruments", []), f"{p}.instruments"))
                    ),
                    self._map(raw.get("provider", {}), f"{p}.provider"),
                    self._map(raw.get("extensions", {}), f"{p}.extensions"),
                )
            )
        return tuple(result)

    def _sources(self, values: list[OnlyJsonValue]) -> tuple[OnlyDataSourceRuntimeConfig, ...]:
        result = []
        for i, value in enumerate(values):
            p = f"$.data_sources[{i}]"
            raw = self._map(value, p)
            coverage = self._map(raw.get("coverage"), f"{p}.coverage")
            result.append(
                OnlyDataSourceRuntimeConfig(
                    OnlyMarketDataSourceId(self._str(raw.get("source_id"), f"{p}.source_id")),
                    self._plugin_id(raw, p),
                    self._bool(raw.get("enabled", True), f"{p}.enabled"),
                    OnlyDataVersion(self._str(raw.get("data_version"), f"{p}.data_version")),
                    OnlyDataSourceCoverageConfig(
                        tuple(
                            self._str(x, f"{p}.coverage.universe_ids[{j}]")
                            for j, x in enumerate(
                                self._list(coverage.get("universe_ids", []), f"{p}.coverage.universe_ids")
                            )
                        ),
                        tuple(
                            _instrument_id(
                                self._str(x, f"{p}.coverage.instrument_ids[{j}]"),
                                f"{p}.coverage.instrument_ids[{j}]",
                            )
                            for j, x in enumerate(
                                self._list(coverage.get("instrument_ids", []), f"{p}.coverage.instrument_ids")
                            )
                        ),
                    ),
                    self._int(raw.get("batch_size", 1024), f"{p}.batch_size", 1),
                    self._map(raw.get("extensions", {}), f"{p}.extensions"),
                )
            )
        return tuple(result)

    def _accounts(
        self, values: list[OnlyJsonValue], base_currency: OnlyCurrency
    ) -> tuple[OnlyAccountRuntimeConfig, ...]:
        result = []
        for i, value in enumerate(values):
            p = f"$.accounts[{i}]"
            raw = self._map(value, p)
            cash = self._map(raw.get("initial_cash"), f"{p}.initial_cash")
            currency = OnlyCurrency(
                self._str(cash.get("currency", base_currency.code), f"{p}.initial_cash.currency"),
                base_currency.precision,
                base_currency.currency_type,
            )
            result.append(
                OnlyAccountRuntimeConfig(
                    OnlyAccountId(self._str(raw.get("account_id"), f"{p}.account_id")),
                    OnlyBrokerGatewayId(self._str(raw.get("gateway_id"), f"{p}.gateway_id")),
                    OnlyMoney(
                        self._decimal(cash.get("value"), f"{p}.initial_cash.value", non_negative=True),
                        currency,
                    ),
                )
            )
        return tuple(result)

    def _brokers(self, values: list[OnlyJsonValue]) -> tuple[OnlyBrokerRuntimeConfig, ...]:
        result = []
        for i, value in enumerate(values):
            p = f"$.brokers[{i}]"
            raw = self._map(value, p)
            result.append(
                OnlyBrokerRuntimeConfig(
                    OnlyBrokerGatewayId(self._str(raw.get("gateway_id"), f"{p}.gateway_id")),
                    self._plugin_id(raw, p),
                    self._bool(raw.get("enabled", True), f"{p}.enabled"),
                    self._map(raw.get("extensions", {}), f"{p}.extensions"),
                )
            )
        return tuple(result)

    def _clusters(self, values: list[OnlyJsonValue]) -> tuple[OnlyClusterImportConfig, ...]:
        return tuple(
            self._cluster(self._map(value, f"$.clusters[{i}]"), f"$.clusters[{i}]") for i, value in enumerate(values)
        )

    def _cluster(self, raw: OnlyJsonMapping, path: str) -> OnlyClusterImportConfig:
        strategy = self._map(raw.get("strategy"), f"{path}.strategy")
        metadata_raw = self._map(raw.get("metadata", {}), f"{path}.metadata")
        return OnlyClusterImportConfig(
            OnlyClusterId(self._str(raw.get("cluster_id"), f"{path}.cluster_id")),
            OnlyAccountId(self._str(raw.get("account_id"), f"{path}.account_id")),
            self._bool(raw.get("enabled", True), f"{path}.enabled"),
            OnlyStrategyImportConfig(
                self._str(strategy.get("class_path"), f"{path}.strategy.class_path"),
                self._str(strategy.get("config_path"), f"{path}.strategy.config_path"),
                self._map(strategy.get("extensions", {}), f"{path}.strategy.extensions"),
            ),
            tuple(
                self._factor(self._map(item, f"{path}.factors[{i}]"), f"{path}.factors[{i}]")
                for i, item in enumerate(self._list(raw.get("factors", []), f"{path}.factors"))
            ),
            None
            if raw.get("risk_profile_id") is None
            else self._str(raw.get("risk_profile_id"), f"{path}.risk_profile_id"),
            MappingProxyType({k: self._str(v, f"{path}.metadata.{k}") for k, v in metadata_raw.items()}),
        )

    def _factor(self, raw: OnlyJsonMapping, path: str) -> OnlyFactorImportConfig:
        subscriptions = self._map(raw.get("subscriptions"), f"{path}.subscriptions")
        instrument_bars = tuple(
            self._instrument_bar(
                self._map(item, f"{path}.subscriptions.instrument_bars[{i}]"),
                f"{path}.subscriptions.instrument_bars[{i}]",
            )
            for i, item in enumerate(
                self._list(subscriptions.get("instrument_bars", []), f"{path}.subscriptions.instrument_bars")
            )
        )
        universe_bars = tuple(
            self._universe_bar(
                self._map(item, f"{path}.subscriptions.universe_bars[{i}]"), f"{path}.subscriptions.universe_bars[{i}]"
            )
            for i, item in enumerate(
                self._list(subscriptions.get("universe_bars", []), f"{path}.subscriptions.universe_bars")
            )
        )
        indicators = tuple(
            OnlyIndicatorSpecConfig(
                OnlyIndicatorId(self._str(item.get("indicator_id"), f"{p}.indicator_id")),
                OnlyIndicatorTypeId(self._str(item.get("type"), f"{p}.type")),
                self._map(item.get("parameters", {}), f"{p}.parameters"),
            )
            for i, value in enumerate(self._list(raw.get("indicators", []), f"{path}.indicators"))
            for p in (f"{path}.indicators[{i}]",)
            for item in (self._map(value, p),)
        )
        return OnlyFactorImportConfig(
            OnlyFactorId(self._str(raw.get("factor_id"), f"{path}.factor_id")),
            self._str(raw.get("factor_type"), f"{path}.factor_type").upper(),
            self._str(raw.get("class_path"), f"{path}.class_path"),
            self._str(raw.get("config_path"), f"{path}.config_path"),
            OnlyStrategySubscriptionConfig(instrument_bars, universe_bars),
            indicators,
            tuple(
                OnlyFactorId(self._str(item, f"{path}.dependencies[{i}]"))
                for i, item in enumerate(self._list(raw.get("dependencies", []), f"{path}.dependencies"))
            ),
            self._bool(raw.get("required", True), f"{path}.required"),
            self._map(raw.get("extensions", {}), f"{path}.extensions"),
        )

    def _instrument_bar(self, raw: OnlyJsonMapping, path: str) -> OnlyInstrumentBarSubscriptionConfig:
        return OnlyInstrumentBarSubscriptionConfig(
            _instrument_id(self._str(raw.get("instrument_id"), f"{path}.instrument_id"), f"{path}.instrument_id"),
            self._bar_spec(
                self._map(raw.get("bar_specification"), f"{path}.bar_specification"), f"{path}.bar_specification"
            ),
            OnlySubscriptionRole(self._str(raw.get("role", "AUXILIARY"), f"{path}.role")),
        )

    def _universe_bar(self, raw: OnlyJsonMapping, path: str) -> OnlyUniverseBarSubscriptionConfig:
        return OnlyUniverseBarSubscriptionConfig(
            self._str(raw.get("universe_id"), f"{path}.universe_id"),
            self._bar_spec(
                self._map(raw.get("bar_specification"), f"{path}.bar_specification"), f"{path}.bar_specification"
            ),
            OnlySubscriptionRole(self._str(raw.get("role", "AUXILIARY"), f"{path}.role")),
        )

    def _bar_spec(self, raw: OnlyJsonMapping, path: str) -> OnlyBarSpecificationConfig:
        aggregation = self._str(raw.get("aggregation"), f"{path}.aggregation")
        # 配置层允许 MINUTE/HOUR/DAY，当前 Domain 统一映射到 TIME。
        aggregation = {
            "MINUTE": "TIME",
            "HOUR": "TIME",
            "DAY": "TIME",
            "WEEK": "TIME",
            "MONTH": "TIME",
        }.get(aggregation, aggregation)
        return OnlyBarSpecificationConfig(
            self._int(raw.get("step"), f"{path}.step", 1),
            OnlyBarAggregation(aggregation),
            OnlyPriceType(self._str(raw.get("price_type", "LAST"), f"{path}.price_type")),
            OnlyAggregationSource(self._str(raw.get("source", "EXTERNAL"), f"{path}.source")),
        )

    def _output(self, raw: OnlyJsonMapping) -> OnlyOutputConfig:
        unknown = set(raw) - {"formats", "overwrite"}
        if unknown:
            raise OnlyClusterConfigError(f"$.output UNKNOWN_FIELD: {sorted(unknown)[0]}")
        return OnlyOutputConfig(
            tuple(
                self._str(x, f"$.output.formats[{i}]").upper()
                for i, x in enumerate(self._list(raw.get("formats", ["JSON"]), "$.output.formats"))
            ),
            self._bool(raw.get("overwrite", False), "$.output.overwrite"),
        )

    def _plugin_id(self, raw: OnlyJsonMapping, path: str) -> str:
        plugin = raw.get("plugin")
        if "type" in raw:
            raise OnlyClusterConfigError(f"{path} UNKNOWN_FIELD: type")
        if plugin is None:
            raise OnlyClusterConfigError(f"{path}.plugin is required")
        return self._str(plugin, f"{path}.plugin").lower()

    @staticmethod
    def _map(value: object, path: str) -> OnlyJsonMapping:
        if not isinstance(value, Mapping):
            raise OnlyClusterConfigError(f"{path} must be a mapping")
        return _normalize_mapping(value, path)

    @staticmethod
    def _list(value: object, path: str) -> list[OnlyJsonValue]:
        if not isinstance(value, list):
            raise OnlyClusterConfigError(f"{path} must be a list")
        return value

    @staticmethod
    def _str(value: object, path: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OnlyClusterConfigError(f"{path} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _bool(value: object, path: str) -> bool:
        if not isinstance(value, bool):
            raise OnlyClusterConfigError(f"{path} must be boolean")
        return value

    @staticmethod
    def _int(value: object, path: str, minimum: int) -> int:
        if isinstance(value, bool):
            raise OnlyClusterConfigError(f"{path} must be integer")
        try:
            result = int(str(value))
        except (TypeError, ValueError) as exc:
            raise OnlyClusterConfigError(f"{path} must be integer") from exc
        if result < minimum:
            raise OnlyClusterConfigError(f"{path} must be >= {minimum}")
        return result

    @staticmethod
    def _decimal(value: object, path: str, *, positive: bool = False, non_negative: bool = False) -> Decimal:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise OnlyClusterConfigError(f"{path} must be decimal") from exc
        if not result.is_finite():
            raise OnlyClusterConfigError(f"{path} must be finite")
        if positive and result <= 0:
            raise OnlyClusterConfigError(f"{path} must be > 0")
        if non_negative and result < 0:
            raise OnlyClusterConfigError(f"{path} must be >= 0")
        return result

    @staticmethod
    def _optional_utc(value: object, path: str) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise OnlyClusterConfigError(f"{path} must be ISO-8601 UTC string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError as exc:
            raise OnlyClusterConfigError(f"{path} invalid timestamp") from exc
        only_require_utc(parsed, path)
        return parsed
