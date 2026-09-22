from __future__ import annotations

from typing import cast

import pytest

from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeResolver
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.runtime.defaults import only_default_engine_services


def test_factory_receives_discovered_registries_and_injects_resolver() -> None:
    resolver = cast(OnlyIntegrationRuntimeResolver, object())
    seen: list[tuple[OnlyDataSourceFactoryRegistry, OnlyBrokerFactoryRegistry]] = []

    def factory(
        data_sources: OnlyDataSourceFactoryRegistry, brokers: OnlyBrokerFactoryRegistry
    ) -> OnlyIntegrationRuntimeResolver:
        seen.append((data_sources, brokers))
        return resolver

    services = only_default_engine_services(fail_fast=True, integration_runtime_resolver_factory=factory)

    assert len(seen) == 1
    assert seen[0][0] is services.assembler.components.data_sources
    assert seen[0][1] is services.assembler.components.brokers
    assert services.assembler.components.integration_runtime_resolver is resolver


def test_resolver_and_factory_together_raise_conflict() -> None:
    with pytest.raises(ValueError, match="INTEGRATION_RUNTIME_COMPOSITION_CONFLICT"):
        only_default_engine_services(
            integration_runtime_resolver=cast(OnlyIntegrationRuntimeResolver, object()),
            integration_runtime_resolver_factory=lambda data_sources, brokers: cast(
                OnlyIntegrationRuntimeResolver, object()
            ),
        )
