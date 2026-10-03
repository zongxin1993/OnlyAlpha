"""Narrow batch backend SPI and exact RESEARCH resolver."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationDefinition
from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest
from onlyalpha.calculation.registry import OnlyCalculationRegistry

from .errors import OnlyResearchCalculationError
from .publication import OnlyResearchCalculationPublicationContract
from .readiness import OnlyResearchOutputReadiness


@runtime_checkable
class OnlyResearchCalculationBackend(Protocol):
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]: ...


@dataclass(frozen=True, slots=True)
class OnlyResolvedResearchCalculationBackend:
    provider: OnlyResearchCalculationBackend
    implementation_manifest: OnlyCalculationImplementationManifest


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationBackendExecutionV2:
    outputs: Mapping[str, pa.Array | pa.ChunkedArray]
    readiness: Mapping[str, OnlyResearchOutputReadiness]


@runtime_checkable
class OnlyResearchReadinessCalculationBackend(Protocol):
    def execute_with_readiness(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> OnlyResearchCalculationBackendExecutionV2: ...


@dataclass(frozen=True, slots=True)
class OnlyResolvedResearchReadinessCalculationBackend:
    provider: OnlyResearchReadinessCalculationBackend
    implementation_manifest: OnlyCalculationImplementationManifest


class OnlyResearchCalculationBackendResolver:
    """Resolve the exact RESEARCH provider without version or backend fallback."""

    def __init__(self, registry: OnlyCalculationRegistry) -> None:
        self._registry = registry

    def resolve(self, definition: OnlyCalculationDefinition) -> OnlyResolvedResearchCalculationBackend:
        try:
            registration = self._registry.resolve(
                definition.kind,
                definition.type_id,
                definition.semantic_version,
                OnlyCalculationBackendKind.RESEARCH,
            )
        except ValueError as exc:
            raise OnlyResearchCalculationError("RESEARCH_BACKEND_UNAVAILABLE", str(exc)) from exc
        provider = registration.provider
        if not callable(getattr(provider, "execute", None)):
            raise OnlyResearchCalculationError(
                "RESEARCH_BACKEND_INVALID", "RESEARCH calculation backend provider must define execute()"
            )
        manifest = registration.implementation_manifest
        if manifest is None:
            raise OnlyResearchCalculationError(
                "RESEARCH_IMPLEMENTATION_IDENTITY_UNRESOLVED",
                f"{definition.type_id}@{definition.semantic_version}",
            )
        return OnlyResolvedResearchCalculationBackend(cast(OnlyResearchCalculationBackend, provider), manifest)

    def resolve_readiness(
        self,
        definition: OnlyCalculationDefinition,
        publication: OnlyResearchCalculationPublicationContract,
    ) -> OnlyResolvedResearchReadinessCalculationBackend:
        try:
            registration = self._registry.resolve(
                definition.kind,
                definition.type_id,
                definition.semantic_version,
                OnlyCalculationBackendKind.RESEARCH,
            )
        except ValueError as exc:
            raise OnlyResearchCalculationError("RESEARCH_READINESS_BACKEND_UNAVAILABLE", str(exc)) from exc
        if publication.readiness_contract_version not in registration.readiness_contract_versions:
            raise OnlyResearchCalculationError(
                "RESEARCH_READINESS_BACKEND_UNAVAILABLE",
                f"{definition.type_id}@{definition.semantic_version}: readiness {publication.readiness_contract_version}",
            )
        provider = registration.provider
        if not callable(getattr(provider, "execute_with_readiness", None)):
            raise OnlyResearchCalculationError(
                "RESEARCH_BACKEND_INVALID", "RESEARCH readiness backend provider must define execute_with_readiness()"
            )
        manifest = registration.implementation_manifest
        if manifest is None:
            raise OnlyResearchCalculationError(
                "RESEARCH_IMPLEMENTATION_IDENTITY_UNRESOLVED",
                f"{definition.type_id}@{definition.semantic_version}",
            )
        return OnlyResolvedResearchReadinessCalculationBackend(
            cast(OnlyResearchReadinessCalculationBackend, provider), manifest
        )
