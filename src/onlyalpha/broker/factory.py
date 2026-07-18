"""Strongly typed Broker factories and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.broker.virtual.config import OnlyVirtualBrokerConfig
from onlyalpha.config import OnlyAccountRuntimeConfig, OnlyBrokerRuntimeConfig, OnlyRuntimeAssemblyPlan


@dataclass(frozen=True, slots=True)
class OnlyBrokerBuildRequest:
    config: OnlyBrokerRuntimeConfig
    account: OnlyAccountRuntimeConfig
    assembly_plan: OnlyRuntimeAssemblyPlan


class OnlyBrokerFactory(Protocol):
    @property
    def factory_id(self) -> str: ...

    def create(self, request: OnlyBrokerBuildRequest) -> OnlyVirtualBrokerConfig: ...


class OnlyBrokerFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, OnlyBrokerFactory] = {}

    def register(self, factory: OnlyBrokerFactory) -> None:
        key = factory.factory_id.upper()
        if key in self._factories:
            raise ValueError(f"duplicate Broker factory: {key}")
        self._factories[key] = factory

    def require(self, factory_id: str) -> OnlyBrokerFactory:
        try:
            return self._factories[factory_id.upper()]
        except KeyError as exc:
            raise ValueError(f"BROKER_FACTORY_NOT_AVAILABLE: {factory_id}") from exc
