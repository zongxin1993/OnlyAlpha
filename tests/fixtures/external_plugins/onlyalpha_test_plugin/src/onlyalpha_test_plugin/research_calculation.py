"""External-style deterministic RESEARCH Calculation plugin fixture."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterSchema,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)

EXTERNAL_IDENTITY = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.INDICATOR,
    "onlyalpha.test.external.identity",
    "1",
    OnlyParameterSchema(),
    (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, False),),
    (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, False),),
    OnlyMissingValuePolicy.FAIL,
    OnlyTimestampSemantic.EVENT_TIME,
    OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_HALF_EVEN"),
)

_WARMUP = OnlyWarmupDefinition(1, "declared input is available", OnlyPreReadyOutput.NULL, "DIRECT")


@dataclass(frozen=True, slots=True)
class OnlyExternalIdentityDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition = EXTERNAL_IDENTITY

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        return self.type_definition.resolve(parameters, input_bindings, _WARMUP)


class OnlyExternalIdentityResearchBackend:
    """A stateless process-reusable provider with execution-local output."""

    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]:
        if definition.type_id != EXTERNAL_IDENTITY.type_id or definition.semantic_version != "1":
            raise ValueError("external identity backend received a different semantic type")
        if set(inputs) != {"value"}:
            raise ValueError("external identity backend requires the exact value input")
        values = inputs["value"]
        if not pa.types.is_decimal(values.type) or values.null_count:
            raise ValueError("external identity backend requires complete Arrow Decimal input")
        return {"value": values.combine_chunks() if isinstance(values, pa.ChunkedArray) else values}


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    package_root = Path(__file__).resolve().parent
    return (
        OnlyCalculationBackendRegistration(
            EXTERNAL_IDENTITY,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyExternalIdentityResearchBackend(),
            OnlyExternalIdentityDefinitionResolver(),
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(
                    EXTERNAL_IDENTITY.kind,
                    EXTERNAL_IDENTITY.type_id,
                    EXTERNAL_IDENTITY.semantic_version,
                ),
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity=("onlyalpha_test_plugin.research_calculation:OnlyExternalIdentityResearchBackend"),
                package_root=package_root,
                resource_paths=("research_calculation.py",),
                semantic_dependencies=(
                    only_python_stdlib_semantic_dependency("decimal"),
                    only_distribution_semantic_dependency("pyarrow"),
                ),
            ),
        ),
    )


__all__ = ["EXTERNAL_IDENTITY", "OnlyExternalIdentityResearchBackend", "registrations"]
