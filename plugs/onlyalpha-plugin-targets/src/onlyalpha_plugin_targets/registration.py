"""Canonical Forward Return Target definition and exact RESEARCH registration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.calculation import (
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
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
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.implementation import (
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha_plugin_targets.research import OnlyOfficialResearchTargetBackend

_NUMERIC = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=38,
    output_quantum=Decimal("0.000000000001"),
    rounding="ROUND_HALF_EVEN",
)

FORWARD_RETURN = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.TARGET,
    "onlyalpha.target.forward_return",
    "1",
    OnlyParameterSchema(
        (
            OnlyParameterDefinition("entry_offset", OnlyParameterType.INTEGER, False, 0, 0),
            OnlyParameterDefinition("exit_offset", OnlyParameterType.INTEGER, True, minimum=1),
        )
    ),
    (
        OnlyInputDefinition("entry_price", OnlyCalculationDataType.DECIMAL, False, semantic_type="PRICE"),
        OnlyInputDefinition("exit_price", OnlyCalculationDataType.DECIMAL, False, semantic_type="PRICE"),
    ),
    (
        OnlyOutputDefinition(
            "target_value",
            OnlyCalculationDataType.DECIMAL,
            True,
            semantic_type=TARGET_VALUE_SEMANTIC_TYPE,
            unit="RATIO",
        ),
    ),
    OnlyMissingValuePolicy.FAIL,
    OnlyTimestampSemantic.EVENT_TIME,
    _NUMERIC,
)


@dataclass(frozen=True, slots=True)
class OnlyOfficialTargetDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        normalized = self.type_definition.parameters.normalize(parameters)
        entry_offset = normalized["entry_offset"]
        exit_offset = normalized["exit_offset"]
        if not isinstance(entry_offset, int) or not isinstance(exit_offset, int) or exit_offset <= entry_offset:
            raise ValueError("Forward Return requires exit_offset > entry_offset >= 0")
        if any(reference.node_fingerprint is not None for reference in input_bindings.values()):
            raise ValueError("Forward Return V1 accepts only external Dataset source bindings")
        return self.type_definition.resolve(
            normalized,
            input_bindings,
            OnlyWarmupDefinition(
                1,
                "entry and exit bar offsets exist on the canonical instrument axis",
                OnlyPreReadyOutput.NULL,
                "INSUFFICIENT_FUTURE_IS_NULL",
            ),
        )


def resolve_forward_return(
    parameters: Mapping[str, object],
    entry_price: OnlyCalculationReference,
    exit_price: OnlyCalculationReference,
) -> OnlyCalculationDefinition:
    return OnlyOfficialTargetDefinitionResolver(FORWARD_RETURN).resolve(
        parameters,
        {"entry_price": entry_price, "exit_price": exit_price},
    )


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    package_root = Path(__file__).resolve().parent
    return (
        OnlyCalculationBackendRegistration(
            FORWARD_RETURN,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyOfficialResearchTargetBackend(),
            OnlyOfficialTargetDefinitionResolver(FORWARD_RETURN),
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(
                    FORWARD_RETURN.kind,
                    FORWARD_RETURN.type_id,
                    FORWARD_RETURN.semantic_version,
                ),
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity="onlyalpha_plugin_targets.research:OnlyOfficialResearchTargetBackend",
                package_root=package_root,
                resource_paths=("registration.py", "research.py"),
                semantic_dependencies=(
                    only_python_stdlib_semantic_dependency("decimal"),
                    only_distribution_semantic_dependency("pyarrow"),
                ),
            ),
        ),
    )
