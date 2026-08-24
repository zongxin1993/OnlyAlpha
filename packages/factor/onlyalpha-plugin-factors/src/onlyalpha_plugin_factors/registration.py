"""Canonical official Factor definitions and exact RESEARCH registrations."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
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
from onlyalpha.calculation.implementation import only_python_implementation_manifest
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha_plugin_factors.research import OnlyOfficialResearchFactorBackend
from onlyalpha_plugin_factors.trading import OnlyOfficialTradingFactorBackendFactory

_NUMERIC = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=28,
    output_quantum=Decimal("0.000000000001"),
    rounding="ROUND_HALF_EVEN",
)

MOMENTUM = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.FACTOR,
    "onlyalpha.factor.momentum",
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

CROSS_SECTION_PERCENTILE = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.FACTOR,
    "onlyalpha.factor.cross_section_percentile",
    "1",
    OnlyParameterSchema(
        (
            OnlyParameterDefinition(
                "direction",
                OnlyParameterType.STRING,
                False,
                "HIGHER_IS_BETTER",
                enum_values=("HIGHER_IS_BETTER", "LOWER_IS_BETTER"),
                uppercase=True,
            ),
            OnlyParameterDefinition(
                "tie_method",
                OnlyParameterType.STRING,
                False,
                "AVERAGE",
                enum_values=("AVERAGE",),
                uppercase=True,
            ),
        )
    ),
    (
        OnlyInputDefinition(
            "factor_value", OnlyCalculationDataType.DECIMAL, True, semantic_type=FACTOR_VALUE_SEMANTIC_TYPE
        ),
    ),
    (
        OnlyOutputDefinition(
            "factor_score", OnlyCalculationDataType.DECIMAL, True, semantic_type=FACTOR_SCORE_SEMANTIC_TYPE
        ),
    ),
    OnlyMissingValuePolicy.PROPAGATE,
    OnlyTimestampSemantic.EVENT_TIME,
    _NUMERIC,
    OnlyFactorKind.CROSS_SECTION,
)

_WARMUP = OnlyWarmupDefinition(1, "declared upstream value is available", OnlyPreReadyOutput.NULL, "UPSTREAM")


@dataclass(frozen=True, slots=True)
class OnlyOfficialFactorDefinitionResolver:
    """Own complete, backend-neutral semantics for one official Factor type."""

    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        return self.type_definition.resolve(parameters, input_bindings, _WARMUP)


def resolve_momentum(
    parameters: Mapping[str, object],
    short: OnlyCalculationReference,
    long: OnlyCalculationReference,
) -> OnlyCalculationDefinition:
    return MOMENTUM.resolve(parameters, {"return_short": short, "return_long": long}, _WARMUP)


def resolve_percentile(parameters: Mapping[str, object], value: OnlyCalculationReference) -> OnlyCalculationDefinition:
    return CROSS_SECTION_PERCENTILE.resolve(parameters, {"factor_value": value}, _WARMUP)


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    backend = OnlyOfficialResearchFactorBackend()
    package_root = Path(__file__).resolve().parent
    resolvers = {item: OnlyOfficialFactorDefinitionResolver(item) for item in (MOMENTUM, CROSS_SECTION_PERCENTILE)}
    research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            backend,
            resolvers[item],
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity="onlyalpha_plugin_factors.research:OnlyOfficialResearchFactorBackend",
                package_root=package_root,
                resource_paths=("registration.py", "research.py"),
            ),
        )
        for item in (MOMENTUM, CROSS_SECTION_PERCENTILE)
    )
    trading = (
        OnlyCalculationBackendRegistration(
            MOMENTUM,
            OnlyCalculationBackendKind.TRADING,
            OnlyOfficialTradingFactorBackendFactory(),
            resolvers[MOMENTUM],
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(
                    MOMENTUM.kind, MOMENTUM.type_id, MOMENTUM.semantic_version
                ),
                backend_kind=OnlyCalculationBackendKind.TRADING,
                entrypoint_identity=("onlyalpha_plugin_factors.trading:OnlyOfficialTradingFactorBackendFactory"),
                package_root=package_root,
                resource_paths=("registration.py", "trading.py"),
            ),
        ),
    )
    return research + trading
