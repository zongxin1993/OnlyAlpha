"""RESEARCH batch backend for neutral internal Predicate semantics."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.predicate import (
    PREDICATE_SEMANTIC_VERSION,
    PREDICATE_TYPE_PREFIX,
    PREDICATE_VALUE_SEMANTIC_TYPE,
    OnlyPredicateDefinitionResolver,
    only_predicate_type_definitions,
    only_predicate_type_reference,  # noqa: F401
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry


class _ResearchPredicateBackend:
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]:
        name = definition.type_id.removeprefix(f"{PREDICATE_TYPE_PREFIX}.")
        if name.startswith("compare."):
            _, operator, _, layout = name.split(".")
            function = {
                "eq": pc.equal,
                "ne": pc.not_equal,
                "lt": pc.less,
                "le": pc.less_equal,
                "gt": pc.greater,
                "ge": pc.greater_equal,
            }[operator]
            left = inputs["left"]
            if layout == "refs":
                right: pa.Array | pa.ChunkedArray | pa.Scalar = inputs["right"]
            else:
                right = pa.scalar(definition.parameters["literal"], type=left.type)
                if definition.parameters["literal_left"]:
                    return {"value": function(right, left)}
            return {"value": function(left, right)}
        if name == "boolean.and":
            return {"value": pc.and_kleene(inputs["left"], inputs["right"])}
        if name == "boolean.or":
            return {"value": pc.or_kleene(inputs["left"], inputs["right"])}
        if name == "boolean.not":
            return {"value": pc.invert(inputs["value"])}
        if name.startswith("terminal."):
            return {"value": inputs["value"]}
        raise ValueError(f"unknown internal Predicate primitive: {name}")


def only_register_research_predicate_primitives(registry: OnlyCalculationRegistry) -> None:
    """Install exact internal RESEARCH registrations without a TRADING runtime backend."""

    package_root = Path(__file__).resolve().parents[2]
    provider = _ResearchPredicateBackend()
    for definition in only_predicate_type_definitions():
        reference = OnlyCalculationTypeReference(
            definition.kind,
            definition.type_id,
            definition.semantic_version,
        )
        registration = OnlyCalculationBackendRegistration(
            definition,
            OnlyCalculationBackendKind.RESEARCH,
            provider,
            OnlyPredicateDefinitionResolver(definition),
            only_python_implementation_manifest(
                calculation_type_reference=reference,
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity="onlyalpha.research.calculation.predicate:_ResearchPredicateBackend",
                package_root=package_root,
                resource_paths=("calculation/predicate.py", "research/calculation/predicate.py"),
                semantic_dependencies=(
                    only_python_stdlib_semantic_dependency("decimal"),
                    only_distribution_semantic_dependency("pyarrow"),
                ),
            ),
        )
        _register_idempotently(registry, registration)


def _register_idempotently(
    registry: OnlyCalculationRegistry,
    registration: OnlyCalculationBackendRegistration,
) -> None:
    definition = registration.type_definition
    try:
        existing = registry.resolve(
            definition.kind,
            definition.type_id,
            definition.semantic_version,
            registration.backend,
        )
    except ValueError as exc:
        if "unknown calculation type" not in str(exc) and "unsupported backend" not in str(exc):
            raise
        registry.register(registration)
    else:
        if (
            existing.type_definition != registration.type_definition
            or existing.backend is not registration.backend
            or type(existing.provider) is not type(registration.provider)
            or existing.definition_resolver != registration.definition_resolver
            or existing.implementation_manifest != registration.implementation_manifest
        ):
            raise ValueError(f"internal Predicate registration conflicts: {definition.type_id}")


__all__ = [
    "PREDICATE_SEMANTIC_VERSION",
    "PREDICATE_VALUE_SEMANTIC_TYPE",
    "only_predicate_type_reference",
    "only_register_research_predicate_primitives",
]
