"""Narrow batch backend SPI and exact RESEARCH resolver."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast, runtime_checkable

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry

from .errors import OnlyResearchCalculationError


@runtime_checkable
class OnlyResearchCalculationBackend(Protocol):
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]: ...


class OnlyResearchCalculationBackendResolver:
    """Resolve the exact RESEARCH provider without version or backend fallback."""

    def __init__(self, registry: OnlyCalculationRegistry) -> None:
        self._registry = registry

    def resolve(self, definition: OnlyCalculationDefinition) -> OnlyResearchCalculationBackend:
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
        return cast(OnlyResearchCalculationBackend, provider)
