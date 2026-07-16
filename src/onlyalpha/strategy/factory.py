"""Strongly typed strategy factories and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.config import OnlyRunConfig, OnlyStrategyImportConfig
from onlyalpha.indicator.base import OnlyIndicatorRegistration


@dataclass(frozen=True, slots=True)
class OnlyStrategyBuildRequest:
    config: OnlyStrategyImportConfig
    run_config: OnlyRunConfig


@dataclass(frozen=True, slots=True)
class OnlyStrategyBuildResult:
    cluster: OnlyCluster
    indicators: tuple[OnlyIndicatorRegistration, ...] = ()


class OnlyStrategyFactory(Protocol):
    @property
    def factory_id(self) -> str: ...

    def create(self, request: OnlyStrategyBuildRequest) -> OnlyStrategyBuildResult: ...


class OnlyStrategyFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, OnlyStrategyFactory] = {}

    def register(self, factory: OnlyStrategyFactory) -> None:
        key = factory.factory_id.upper()
        if key in self._factories:
            raise ValueError(f"duplicate strategy factory: {key}")
        self._factories[key] = factory

    def require(self, factory_id: str) -> OnlyStrategyFactory:
        try:
            return self._factories[factory_id.upper()]
        except KeyError as exc:
            raise ValueError(f"STRATEGY_FACTORY_NOT_AVAILABLE: {factory_id}") from exc
