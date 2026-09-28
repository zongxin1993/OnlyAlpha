"""Operational materialization plan kept outside Dataset semantic identity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.cache.historical.models import OnlyCachePolicy
from onlyalpha.data.historical import OnlyHistoricalDataProviderFactory
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.market_data.resolution import OnlyBarConstructionKind, OnlyBarConstructionRecipe

from .definition import OnlyResearchDatasetDefinition


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetMaterializationPlan:
    definition: OnlyResearchDatasetDefinition
    construction_recipe: OnlyBarConstructionRecipe
    source_id: OnlyMarketDataSourceId
    provider_factory: OnlyHistoricalDataProviderFactory
    plugin_config: object
    instruments: Mapping[OnlyInstrumentId, OnlyInstrument]
    calendars: Mapping[OnlyCalendarId, OnlyTradingCalendar]
    data_version: OnlyDataVersion
    cache_policy: OnlyCachePolicy
    batch_size: int
    config_directory: Path
    plugin_id: str
    plugin_version: str

    def __post_init__(self) -> None:
        if (
            self.construction_recipe.target_semantic != self.definition.bar_semantic
            or self.construction_recipe.kind is not OnlyBarConstructionKind.PROVIDER_NATIVE
        ):
            raise ValueError("DATASET_CONSTRUCTION_RECIPE_UNSUPPORTED")
        if self.batch_size <= 0:
            raise ValueError("DATASET_DEFINITION_INVALID: batch_size must be positive")
