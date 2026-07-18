"""Synthetic DataSource plugin Factory and extension parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import yaml  # type: ignore[import-untyped]

from onlyalpha.data.synthetic.source import (
    ONLY_SYNTHETIC_PLUGIN_DESCRIPTOR,
    OnlySyntheticHistoricalDataSource,
    OnlySyntheticHistoricalDataSourceConfig,
    OnlySyntheticInstrumentDataConfig,
    OnlySyntheticNoiseModel,
    OnlySyntheticPriceSegment,
    OnlySyntheticPriceSegmentType,
    OnlySyntheticVolumeModel,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor


@dataclass(frozen=True, slots=True)
class OnlySyntheticPluginConfig:
    market_config: str
    random_seed: int


class OnlySyntheticDataSourceFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_SYNTHETIC_PLUGIN_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlySyntheticPluginConfig:
        return OnlySyntheticPluginConfig(
            self._string(extensions.get("market_config"), "data_sources[].extensions.market_config"),
            self._integer(extensions.get("random_seed", 0), "random_seed"),
        )

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues: list[OnlyPluginValidationIssue] = []
        capabilities = self.descriptor.capabilities
        if not isinstance(capabilities, OnlyDataSourceCapabilities):
            issues.append(OnlyPluginValidationIssue("PLUGIN_DESCRIPTOR_INVALID", "invalid capabilities"))
        else:
            issues.extend(
                OnlyPluginValidationIssue(
                    "PLUGIN_CAPABILITY_NOT_SUPPORTED",
                    f"Synthetic DataSource does not support {name}",
                    name,
                )
                for name in capabilities.missing(request.requested_capabilities)
            )
        if not isinstance(request.plugin_config, OnlySyntheticPluginConfig):
            issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid Synthetic plugin config"))
        elif not (request.config_directory / request.plugin_config.market_config).is_file():
            issues.append(
                OnlyPluginValidationIssue(
                    "PLUGIN_CONFIG_INVALID",
                    "synthetic market_config does not exist",
                    "market_config",
                )
            )
        return tuple(issues)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlySyntheticHistoricalDataSource:
        config = request.plugin_config
        if not isinstance(config, OnlySyntheticPluginConfig):
            raise TypeError("Synthetic Factory requires OnlySyntheticPluginConfig")
        market_path = (request.config_directory / config.market_config).resolve()
        market = self._mapping(yaml.safe_load(market_path.read_text(encoding="utf-8")), "synthetic market")
        instrument_ids = set(request.coverage.instrument_ids)
        for universe_id in request.coverage.universe_ids:
            universe = next(item for item in request.universes if item.universe_id == universe_id)
            instrument_ids.update(universe.instrument_ids)
        items = tuple(
            self._instrument(request, instrument_id, market) for instrument_id in sorted(instrument_ids, key=str)
        )
        return OnlySyntheticHistoricalDataSource(
            OnlySyntheticHistoricalDataSourceConfig(
                request.source_id,
                request.runtime_id,
                request.data_version,
                items,
                config.random_seed,
            )
        )

    def _instrument(
        self,
        request: OnlyDataSourceCreateRequest,
        instrument_id: OnlyInstrumentId,
        market: Mapping[str, object],
    ) -> OnlySyntheticInstrumentDataConfig:
        instrument = request.instruments[instrument_id]
        if instrument.trading_calendar_id is None:
            raise ValueError(f"synthetic instrument {instrument.instrument_id} requires a TradingCalendar")
        calendar = request.calendars[instrument.trading_calendar_id]
        bar_type = request.bar_types[instrument_id]
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
