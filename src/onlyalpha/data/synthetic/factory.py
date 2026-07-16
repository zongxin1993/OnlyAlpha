"""Synthetic HistoricalDataSource factory and private extension parser."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import yaml  # type: ignore[import-untyped]

from onlyalpha.data.factory import OnlyDataSourceBuildRequest
from onlyalpha.data.synthetic.source import (
    OnlySyntheticHistoricalDataSource,
    OnlySyntheticHistoricalDataSourceConfig,
    OnlySyntheticInstrumentDataConfig,
    OnlySyntheticNoiseModel,
    OnlySyntheticPriceSegment,
    OnlySyntheticPriceSegmentType,
    OnlySyntheticVolumeModel,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


class OnlySyntheticDataSourceFactory:
    @property
    def factory_id(self) -> str:
        return "SYNTHETIC"

    def create(self, request: OnlyDataSourceBuildRequest) -> OnlySyntheticHistoricalDataSource:
        extensions = request.config.extensions
        market_name = self._string(extensions.get("market_config"), "data_sources[].extensions.market_config")
        random_seed = self._integer(extensions.get("random_seed", 0), "random_seed")
        market_path = (request.run_config.source_path.parent / market_name).resolve()
        market = self._mapping(yaml.safe_load(market_path.read_text(encoding="utf-8")), "synthetic market")
        instrument_ids = set(request.config.coverage.instrument_ids)
        for universe_id in request.config.coverage.universe_ids:
            universe = next(item for item in request.run_config.universes if item.universe_id == universe_id)
            instrument_ids.update(universe.instrument_ids)
        items = tuple(
            self._instrument(request, instrument_id, market) for instrument_id in sorted(instrument_ids, key=str)
        )
        return OnlySyntheticHistoricalDataSource(
            OnlySyntheticHistoricalDataSourceConfig(
                request.config.source_id,
                request.runtime_id,
                request.config.data_version,
                items,
                random_seed,
            )
        )

    def _instrument(
        self,
        request: OnlyDataSourceBuildRequest,
        instrument_id: OnlyInstrumentId,
        market: Mapping[str, object],
    ) -> OnlySyntheticInstrumentDataConfig:
        instrument = next(
            item for item in request.run_config.reference_data.instruments if item.instrument_id == instrument_id
        )
        if instrument.trading_calendar_id is None:
            raise ValueError(f"synthetic instrument {instrument.instrument_id} requires a TradingCalendar")
        calendar = request.run_config.reference_data.calendar_by_id[instrument.trading_calendar_id]
        bar_type = self._bar_type(request, instrument.instrument_id)
        segments = tuple(
            OnlySyntheticPriceSegment(
                OnlySyntheticPriceSegmentType(self._string(item.get("type"), "segment.type")),
                self._integer(item.get("duration_bars"), "segment.duration_bars"),
                None if item.get("end_price") is None else Decimal(str(item["end_price"])),
                Decimal(str(item.get("amplitude", "0"))),
                self._integer(item.get("cycle_length", 10), "segment.cycle_length"),
                Decimal(str(item.get("volatility", "0.02"))),
                Decimal(str(item.get("volume_multiplier", "1"))),
            )
            for raw in self._list(market.get("segments"), "segments")
            for item in (self._mapping(raw, "segment"),)
        )
        volume = self._mapping(market.get("volume"), "volume")
        noise = self._mapping(market.get("noise", {}), "noise")
        return OnlySyntheticInstrumentDataConfig(
            instrument,
            calendar,
            bar_type,
            OnlyPrice(Decimal(str(market["initial_price"])), instrument.price_precision),
            segments,
            OnlySyntheticVolumeModel(
                OnlyQuantity(Decimal(str(volume["base_volume"])), instrument.quantity_precision),
                self._integer(volume.get("variation_steps", 0), "volume.variation_steps"),
            ),
            OnlySyntheticNoiseModel(
                bool(noise.get("enabled", False)),
                self._integer(noise.get("maximum_price_steps", 0), "noise.maximum_price_steps"),
            ),
        )

    @staticmethod
    def _bar_type(request: OnlyDataSourceBuildRequest, instrument_id: OnlyInstrumentId) -> OnlyBarType:
        for strategy in request.run_config.strategies:
            for instrument_subscription in strategy.common.subscriptions.instrument_bars:
                if instrument_subscription.instrument_id == instrument_id:
                    return instrument_subscription.bar_specification.to_bar_type(instrument_id)
            for universe_subscription in strategy.common.subscriptions.universe_bars:
                universe = next(
                    x for x in request.run_config.universes if x.universe_id == universe_subscription.universe_id
                )
                if instrument_id in universe.instrument_ids:
                    return universe_subscription.bar_specification.to_bar_type(instrument_id)
        raise ValueError(f"no Bar subscription for synthetic instrument {instrument_id}")

    @staticmethod
    def _mapping(value: object, path: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{path} must be a mapping")
        return value

    @staticmethod
    def _list(value: object, path: str) -> list[object]:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be a list")
        return value

    @staticmethod
    def _string(value: object, path: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path} must be a non-empty string")
        return value

    @staticmethod
    def _integer(value: object, path: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        try:
            return int(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must be an integer") from exc
