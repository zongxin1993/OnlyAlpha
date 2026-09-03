"""Canonical example Momentum Factor and exact backend registrations."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.calculation import (
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
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
    OnlyCalculationStateCapability,
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha_example_alpha.research import OnlyExampleResearchMomentumBackend
from onlyalpha_example_alpha.trading import OnlyExampleTradingMomentumBackendFactory

_NUMERIC = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=28,
    output_quantum=Decimal("0.000000000001"),
    rounding="ROUND_HALF_EVEN",
)

MOMENTUM = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.FACTOR,
    "example.factor.momentum",
    "1",
    OnlyParameterSchema(
        (
            OnlyParameterDefinition("short_weight", OnlyParameterType.DECIMAL, False, Decimal("0.5")),
            OnlyParameterDefinition("long_weight", OnlyParameterType.DECIMAL, False, Decimal("0.5")),
        )
    ),
    (
        OnlyInputDefinition("return_short", OnlyCalculationDataType.DECIMAL, True),
        OnlyInputDefinition("return_long", OnlyCalculationDataType.DECIMAL, True),
    ),
    (
        OnlyOutputDefinition(
            "factor_value", OnlyCalculationDataType.DECIMAL, True, semantic_type=FACTOR_VALUE_SEMANTIC_TYPE
        ),
    ),
    OnlyMissingValuePolicy.PROPAGATE,
    OnlyTimestampSemantic.EVENT_TIME,
    _NUMERIC,
    OnlyFactorKind.TIME_SERIES,
)


@dataclass(frozen=True, slots=True)
class OnlyExampleMomentumDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition = MOMENTUM

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        return self.type_definition.resolve(
            parameters,
            input_bindings,
            OnlyWarmupDefinition(1, "declared upstream values are available", OnlyPreReadyOutput.NULL, "UPSTREAM"),
        )


def resolve_momentum(
    parameters: Mapping[str, object],
    short: OnlyCalculationReference,
    long: OnlyCalculationReference,
) -> OnlyCalculationDefinition:
    return OnlyExampleMomentumDefinitionResolver().resolve(parameters, {"return_short": short, "return_long": long})


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    package_root = Path(__file__).resolve().parent
    resolver = OnlyExampleMomentumDefinitionResolver()
    reference = OnlyCalculationTypeReference(MOMENTUM.kind, MOMENTUM.type_id, MOMENTUM.semantic_version)
    return (
        OnlyCalculationBackendRegistration(
            MOMENTUM,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyExampleResearchMomentumBackend(),
            resolver,
            only_python_implementation_manifest(
                calculation_type_reference=reference,
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity="onlyalpha_example_alpha.research:OnlyExampleResearchMomentumBackend",
                package_root=package_root,
                resource_paths=("registration.py", "research.py"),
                semantic_dependencies=(
                    only_python_stdlib_semantic_dependency("decimal"),
                    only_distribution_semantic_dependency("pyarrow"),
                ),
            ),
        ),
        OnlyCalculationBackendRegistration(
            MOMENTUM,
            OnlyCalculationBackendKind.TRADING,
            OnlyExampleTradingMomentumBackendFactory(),
            resolver,
            only_python_implementation_manifest(
                calculation_type_reference=reference,
                backend_kind=OnlyCalculationBackendKind.TRADING,
                entrypoint_identity="onlyalpha_example_alpha.trading:OnlyExampleTradingMomentumBackendFactory",
                package_root=package_root,
                resource_paths=("registration.py", "trading.py"),
                semantic_dependencies=(only_python_stdlib_semantic_dependency("decimal"),),
            ),
            OnlyCalculationStateCapability.STATELESS,
        ),
    )
