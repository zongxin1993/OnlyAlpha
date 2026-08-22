"""Canonical semantic capability projection for deployment conformance."""

from __future__ import annotations

from dataclasses import dataclass

from .definition import OnlyCalculationBackendKind, OnlyCalculationTypeDefinition
from .registry import OnlyCalculationRegistry


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationSemanticCapability:
    """One backend-visible semantic contract without provider provenance."""

    backend: OnlyCalculationBackendKind
    type_definition: OnlyCalculationTypeDefinition


def only_calculation_capability_projection(
    registry: OnlyCalculationRegistry,
    backend: OnlyCalculationBackendKind,
) -> tuple[OnlyCalculationSemanticCapability, ...]:
    """Project exact backend-visible contracts in stable semantic order."""

    capabilities: list[OnlyCalculationSemanticCapability] = []
    for definition in registry.type_definitions():
        try:
            registry.resolve(definition.kind, definition.type_id, definition.semantic_version, backend)
        except ValueError:
            continue
        capabilities.append(OnlyCalculationSemanticCapability(backend, definition))
    return tuple(
        sorted(
            capabilities,
            key=lambda item: (
                item.type_definition.kind.value,
                item.type_definition.type_id,
                item.type_definition.semantic_version,
            ),
        )
    )


def only_assert_calculation_capabilities_equivalent(
    expected: tuple[OnlyCalculationSemanticCapability, ...],
    actual: tuple[OnlyCalculationSemanticCapability, ...],
) -> None:
    """Fail closed when two process compositions expose different semantics."""

    if actual != expected:
        raise ValueError("Calculation semantic capability mismatch")


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
