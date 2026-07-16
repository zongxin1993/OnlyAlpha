"""Runtime-agnostic assembly boundary; concrete selection is delegated to registries."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.config import OnlyRunConfig
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult, OnlyRuntimeFactoryRegistry


@dataclass(frozen=True, slots=True)
class OnlyComponentFactoryRegistries:
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    clusters: OnlyClusterFactory


class OnlyEngineRunAssembler:
    def __init__(
        self,
        runtime_factories: OnlyRuntimeFactoryRegistry,
        component_factories: OnlyComponentFactoryRegistries,
    ) -> None:
        self._runtime_factories = runtime_factories
        self._component_factories = component_factories

    def build(self, config: OnlyRunConfig) -> OnlyRuntimeBuildResult:
        try:
            factory = self._runtime_factories.require(config.runtime.runtime_type)
        except ValueError as exc:
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_FACTORY_NOT_AVAILABLE",
                failure_message=str(exc),
            )
        return factory.create(OnlyRuntimeBuildRequest(config, self._component_factories))
