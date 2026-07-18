"""Strongly typed market-data source factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.config import OnlyDataSourceRuntimeConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.data.ports import OnlyHistoricalDataSource
from onlyalpha.domain.identifiers import OnlyRuntimeId


@dataclass(frozen=True, slots=True)
class OnlyDataSourceBuildRequest:
    config: OnlyDataSourceRuntimeConfig
    assembly_plan: OnlyRuntimeAssemblyPlan
    runtime_id: OnlyRuntimeId


class OnlyDataSourceFactory(Protocol):
    @property
    def factory_id(self) -> str: ...

    def create(self, request: OnlyDataSourceBuildRequest) -> OnlyHistoricalDataSource: ...


class OnlyDataSourceFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, OnlyDataSourceFactory] = {}

    def register(self, factory: OnlyDataSourceFactory) -> None:
        key = factory.factory_id.upper()
        if key in self._factories:
            raise ValueError(f"duplicate data-source factory: {key}")
        self._factories[key] = factory

    def require(self, factory_id: str) -> OnlyDataSourceFactory:
        try:
            return self._factories[factory_id.upper()]
        except KeyError as exc:
            raise ValueError(f"DATA_SOURCE_FACTORY_NOT_AVAILABLE: {factory_id}") from exc
