"""Deterministic read projections over existing Research semantic authorities."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.calculation.binding import (
    OnlyResearchDatasetSourceContract,
    only_research_dataset_source_contracts,
)
from onlyalpha.research.definition.model import OnlyResearchUniverseKind
from onlyalpha.research.definition.ports import (
    OnlyResearchRegisteredUniverse,
    OnlyResearchUniverseCatalog,
)
from onlyalpha.research.evaluation.capability import (
    OnlyResearchStatisticsCapability,
    only_research_statistics_capabilities,
)


@dataclass(frozen=True, slots=True)
class ResearchUniverseDiscovery:
    selection_kinds: tuple[OnlyResearchUniverseKind, ...]
    registered_universes: tuple[OnlyResearchRegisteredUniverse, ...]


class ResearchDiscoveryService:
    def __init__(
        self,
        calculation_registry: OnlyCalculationRegistry,
        universe_catalog: OnlyResearchUniverseCatalog | None = None,
    ) -> None:
        self._calculations = calculation_registry
        self._universes = universe_catalog

    def calculations(self) -> tuple[OnlyCalculationTypeDefinition, ...]:
        result: list[OnlyCalculationTypeDefinition] = []
        for descriptor in self._calculations.descriptors():
            reference = OnlyCalculationTypeReference(
                descriptor["kind"],  # type: ignore[arg-type]
                str(descriptor["type_id"]),
                str(descriptor["semantic_version"]),
            )
            try:
                self._calculations.resolve(
                    reference.kind,
                    reference.type_id,
                    reference.semantic_version,
                    OnlyCalculationBackendKind.RESEARCH,
                )
            except ValueError:
                continue
            result.append(self._calculations.resolve_type(reference))
        return tuple(sorted(result, key=lambda item: (item.kind.value, item.type_id, item.semantic_version)))

    @staticmethod
    def dataset_fields() -> tuple[tuple[str, OnlyResearchDatasetSourceContract], ...]:
        return only_research_dataset_source_contracts()

    def universes(self) -> ResearchUniverseDiscovery:
        registered = () if self._universes is None else self._universes.list_registered()
        registered_kinds = {item.kind for item in registered}
        return ResearchUniverseDiscovery(
            tuple(
                kind
                for kind in OnlyResearchUniverseKind
                if kind
                in {
                    OnlyResearchUniverseKind.SINGLE_INSTRUMENT,
                    OnlyResearchUniverseKind.EXPLICIT_INSTRUMENT_SET,
                    *registered_kinds,
                }
            ),
            tuple(sorted(registered, key=lambda item: (item.kind.value, item.registered_id))),
        )

    @staticmethod
    def statistics() -> tuple[OnlyResearchStatisticsCapability, ...]:
        return tuple(sorted(only_research_statistics_capabilities(), key=lambda item: item.method.value))


__all__ = ["ResearchDiscoveryService", "ResearchUniverseDiscovery"]
