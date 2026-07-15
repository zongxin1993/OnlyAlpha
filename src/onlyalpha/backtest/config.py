"""Typed YAML configuration for the product backtest entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.synthetic import (
    OnlySyntheticHistoricalDataSourceConfig,
    OnlySyntheticInstrumentDataConfig,
    OnlySyntheticNoiseModel,
    OnlySyntheticPriceSegment,
    OnlySyntheticPriceSegmentType,
    OnlySyntheticVolumeModel,
)
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
    OnlyInstrumentId,
    OnlyRawSymbol,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyETF
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone, only_require_utc
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.indicator.base import OnlyIndicatorId
from onlyalpha.indicator.macd import OnlyMacdIndicatorConfig
from onlyalpha.strategies.macd import OnlyMacdExampleConfig


class OnlyBacktestConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyBacktestConfig:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    start_time: datetime
    end_time: datetime
    base_currency: OnlyCurrency
    initial_cash: OnlyMoney
    calendar: OnlyTradingCalendar
    instrument: OnlyETF
    primary_bar_type: OnlyBarType
    synthetic_source: OnlySyntheticHistoricalDataSourceConfig
    macd: OnlyMacdIndicatorConfig
    strategy: OnlyMacdExampleConfig
    broker_gateway_id: OnlyBrokerGatewayId
    fixed_commission: OnlyMoney
    batch_size: int = 1024

    def __post_init__(self) -> None:
        only_require_utc(self.start_time, "backtest start_time")
        only_require_utc(self.end_time, "backtest end_time")
        if self.start_time >= self.end_time or self.batch_size <= 0:
            raise OnlyBacktestConfigError("backtest range must increase and batch_size must be positive")
        if self.initial_cash.currency != self.base_currency or self.fixed_commission.currency != self.base_currency:
            raise OnlyBacktestConfigError("backtest money values must use the base currency")
        if self.synthetic_source.runtime_id != self.runtime_id:
            raise OnlyBacktestConfigError("synthetic source must use the Runtime scope")

    @classmethod
    def load(cls, path: str | Path) -> OnlyBacktestConfig:
        config_path = Path(path).resolve()
        root = cls._mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "backtest config")
        runtime = cls._mapping(root["runtime"], "runtime")
        data = cls._mapping(root["data_source"], "data_source")
        instrument_raw = cls._mapping(root["instrument"], "instrument")
        bars = cls._mapping(root["bars"], "bars")
        strategy_raw = cls._mapping(root["strategy"], "strategy")
        account = cls._mapping(root["account"], "account")
        broker = cls._mapping(root["broker"], "broker")
        commission = cls._mapping(root["commission"], "commission")

        engine_id = OnlyEngineId(str(runtime.get("engine_id", "onlyalpha")))
        runtime_id = OnlyRuntimeId(str(runtime["runtime_id"]))
        account_id = OnlyAccountId(str(account.get("account_id", f"{runtime_id}-DEFAULT")))
        currency = OnlyCurrency(str(runtime.get("base_currency", "CNY")), 2, OnlyCurrencyType.FIAT)
        initial_cash = OnlyMoney(Decimal(str(account["initial_cash"])), currency)
        start_time = cls._utc(str(runtime["start_time"]))
        end_time = cls._utc(str(runtime["end_time"]))

        venue_id = OnlyVenueId(str(instrument_raw["venue"]))
        calendar_id = OnlyCalendarId(str(instrument_raw["trading_calendar"]))
        timezone = OnlyTimeZone(str(instrument_raw["timezone"]))
        sessions = tuple(
            OnlyTradingSession(
                str(item["name"]),
                time.fromisoformat(str(item["opens_at"])),
                time.fromisoformat(str(item["closes_at"])),
                OnlySessionType(str(item.get("session_type", "CONTINUOUS"))),
            )
            for raw_item in cls._list(root["calendar_sessions"], "calendar_sessions")
            for item in (cls._mapping(raw_item, "calendar session"),)
        )
        calendar = OnlyTradingCalendar(
            calendar_id,
            venue_id,
            timezone,
            sessions,
            holidays=tuple(date.fromisoformat(str(item)) for item in cls._list(root.get("holidays", []), "holidays")),
        )
        instrument_id = OnlyInstrumentId(OnlySymbol(str(instrument_raw["symbol"])), venue_id)
        price_precision = int(str(instrument_raw.get("price_precision", 2)))
        quantity_precision = int(str(instrument_raw.get("quantity_precision", 0)))
        instrument = OnlyETF(
            instrument_id=instrument_id,
            raw_symbol=OnlyRawSymbol(str(instrument_raw["symbol"])),
            market_type=OnlyMarketType.CASH,
            quote_currency=currency,
            settlement_currency=currency,
            price_precision=price_precision,
            quantity_precision=quantity_precision,
            tick_size=OnlyPrice(Decimal(str(instrument_raw["price_increment"])), price_precision),
            step_size=OnlyQuantity(Decimal(str(instrument_raw["quantity_increment"])), quantity_precision),
            lot_size=OnlyQuantity(Decimal(str(instrument_raw["lot_size"])), quantity_precision),
            minimum_quantity=OnlyQuantity(Decimal(str(instrument_raw["lot_size"])), quantity_precision),
            maximum_quantity=OnlyQuantity(
                Decimal(str(instrument_raw.get("maximum_quantity", "100000000"))), quantity_precision
            ),
            contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
            trading_calendar_id=calendar_id,
            timezone=timezone.name,
        )
        step = cls._parse_bar_step(str(bars["primary"]))
        bar_type = OnlyBarType(
            instrument_id,
            OnlyBarSpecification(step, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        )

        market_path = (config_path.parent / str(data["market_config"])).resolve()
        market = cls._mapping(yaml.safe_load(market_path.read_text(encoding="utf-8")), "synthetic market config")
        segments = tuple(
            OnlySyntheticPriceSegment(
                OnlySyntheticPriceSegmentType(str(item["type"])),
                int(str(item["duration_bars"])),
                None if item.get("end_price") is None else Decimal(str(item["end_price"])),
                Decimal(str(item.get("amplitude", "0"))),
                int(str(item.get("cycle_length", 10))),
                Decimal(str(item.get("volatility", "0.02"))),
                Decimal(str(item.get("volume_multiplier", "1"))),
            )
            for raw_item in cls._list(market["segments"], "segments")
            for item in (cls._mapping(raw_item, "segment"),)
        )
        volume_raw = cls._mapping(market["volume"], "volume")
        noise_raw = cls._mapping(market.get("noise", {}), "noise")
        synthetic_instrument = OnlySyntheticInstrumentDataConfig(
            instrument,
            calendar,
            bar_type,
            OnlyPrice(Decimal(str(market["initial_price"])), price_precision),
            segments,
            OnlySyntheticVolumeModel(
                OnlyQuantity(Decimal(str(volume_raw["base_volume"])), quantity_precision),
                int(str(volume_raw.get("variation_steps", 0))),
            ),
            OnlySyntheticNoiseModel(
                bool(noise_raw.get("enabled", False)),
                int(str(noise_raw.get("maximum_price_steps", 0))),
            ),
        )
        source_config = OnlySyntheticHistoricalDataSourceConfig(
            OnlyMarketDataSourceId(str(data["source_id"])),
            runtime_id,
            OnlyDataVersion(str(data["data_version"])),
            (synthetic_instrument,),
            int(str(data["random_seed"])),
        )
        indicator_id = OnlyIndicatorId(str(strategy_raw.get("macd_indicator_id", "macd-primary")))
        warmup = int(
            str(
                strategy_raw.get(
                    "warmup_bars",
                    int(str(strategy_raw["slow_period"])) + int(str(strategy_raw["signal_period"])) - 1,
                )
            )
        )
        macd = OnlyMacdIndicatorConfig(
            indicator_id,
            bar_type,
            int(str(strategy_raw["fast_period"])),
            int(str(strategy_raw["slow_period"])),
            int(str(strategy_raw["signal_period"])),
            "close",
            warmup,
        )
        strategy = OnlyMacdExampleConfig(
            OnlyClusterId(str(strategy_raw["cluster_id"])),
            account_id,
            instrument_id,
            bar_type,
            indicator_id,
            OnlyQuantity(Decimal(str(strategy_raw["trade_quantity"])), quantity_precision),
            warmup,
            bool(strategy_raw.get("allow_reentry", False)),
            str(strategy_raw.get("exit_mode", "FULL_AVAILABLE")),
        )
        if str(broker["type"]) != "OnlyVirtualBrokerGateway":
            raise OnlyBacktestConfigError("product backtest requires OnlyVirtualBrokerGateway")
        if str(data["type"]) != "SYNTHETIC":
            raise OnlyBacktestConfigError("this product configuration requires SYNTHETIC data")
        return cls(
            engine_id,
            runtime_id,
            account_id,
            start_time,
            end_time,
            currency,
            initial_cash,
            calendar,
            instrument,
            bar_type,
            source_config,
            macd,
            strategy,
            OnlyBrokerGatewayId(str(broker.get("gateway_id", "virtual-backtest"))),
            OnlyMoney(Decimal(str(commission.get("fixed_amount", "0"))), currency),
            int(str(data.get("batch_size", 1024))),
        )

    @staticmethod
    def _mapping(value: object, name: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise OnlyBacktestConfigError(f"{name} must be a mapping")
        return value

    @staticmethod
    def _list(value: object, name: str) -> list[object]:
        if not isinstance(value, list):
            raise OnlyBacktestConfigError(f"{name} must be a list")
        return value

    @staticmethod
    def _utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        only_require_utc(parsed, "configuration timestamp")
        return parsed

    @staticmethod
    def _parse_bar_step(value: str) -> int:
        if not value.endswith("m") or not value[:-1].isdigit():
            raise OnlyBacktestConfigError("first-phase product backtest requires an Xm TIME Bar")
        return int(value[:-1])
