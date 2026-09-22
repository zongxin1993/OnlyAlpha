"""Single production composition root for the persistence-backed Integration Runtime Resolver.

Bootstrap provisions Integration authority state; this module only loads it. A missing
durable master key fails closed. The type catalog is a projection over the caller's
already-discovered plugin registries — this module performs no plugin discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeGenerationReader,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1

from .config import OnlyPostgresOperationalConnectionOptions
from .credentials import OnlyPostgresCredentialAuthority, only_load_master_key
from .integration_probe_store import OnlyPostgresIntegrationProbeStore
from .integration_store import OnlyPostgresIntegrationStore


@dataclass(frozen=True, slots=True)
class OnlyIntegrationRuntimeCompositionV1:
    postgres_dsn: str
    master_key_path: Path
    connection_options: OnlyPostgresOperationalConnectionOptions | None = None
    runtime_generations: OnlyIntegrationRuntimeGenerationReader | None = None
    component_types: tuple[OnlyIntegrationTypeDescriptorV1, ...] = ()


def only_compose_integration_runtime_resolver(
    composition: OnlyIntegrationRuntimeCompositionV1,
    data_sources: OnlyDataSourceFactoryRegistry,
    brokers: OnlyBrokerFactoryRegistry,
) -> OnlyIntegrationRuntimeResolver:
    master_key = only_load_master_key(composition.master_key_path)
    return OnlyIntegrationRuntimeResolver(
        OnlyPostgresIntegrationStore(composition.postgres_dsn, options=composition.connection_options),
        OnlyPostgresCredentialAuthority(composition.postgres_dsn, master_key, options=composition.connection_options),
        OnlyIntegrationTypeCatalog(data_sources, brokers, composition.component_types),
        probes=OnlyPostgresIntegrationProbeStore(composition.postgres_dsn, options=composition.connection_options),
        runtime_generations=composition.runtime_generations,
    )


__all__ = ["OnlyIntegrationRuntimeCompositionV1", "only_compose_integration_runtime_resolver"]
