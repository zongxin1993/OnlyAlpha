"""Canonical L1 Operator definitions and exact backend registrations."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.calculation import (
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
from onlyalpha_plugin_operators.research import OnlyOfficialResearchOperatorBackend
from onlyalpha_plugin_operators.trading import OnlyOfficialTradingOperatorBackendFactory

_NUMERIC = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=28,
    output_quantum=Decimal("0.000000000001"),
    rounding="ROUND_HALF_EVEN",
)

ROLLING_MEAN = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.INDICATOR,
    "onlyalpha.operator.rolling_mean",
    "1",
    OnlyParameterSchema((OnlyParameterDefinition("period", OnlyParameterType.INTEGER, True, minimum=1),)),
    (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
    (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
    OnlyMissingValuePolicy.PROPAGATE,
    OnlyTimestampSemantic.EVENT_TIME,
    _NUMERIC,
)

CROSS_SECTION_PERCENTILE = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.INDICATOR,
    "onlyalpha.operator.cross_section_percentile",
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
                "tie_method", OnlyParameterType.STRING, False, "AVERAGE", enum_values=("AVERAGE",), uppercase=True
            ),
        )
    ),
    (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
    (OnlyOutputDefinition("percentile", OnlyCalculationDataType.DECIMAL, True),),
    OnlyMissingValuePolicy.PROPAGATE,
    OnlyTimestampSemantic.EVENT_TIME,
    _NUMERIC,
    execution_shape=OnlyFactorKind.CROSS_SECTION,
)


@dataclass(frozen=True, slots=True)
class OnlyOfficialOperatorDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        period = int(str(parameters.get("period", 1))) if self.type_definition is ROLLING_MEAN else 1
        warmup = OnlyWarmupDefinition(
            period,
            "complete declared input window is available" if period > 1 else "declared input is available",
            OnlyPreReadyOutput.NULL,
            "UPSTREAM",
        )
        return self.type_definition.resolve(parameters, input_bindings, warmup)


def resolve_rolling_mean(
    parameters: Mapping[str, object], value: OnlyCalculationReference
) -> OnlyCalculationDefinition:
    return OnlyOfficialOperatorDefinitionResolver(ROLLING_MEAN).resolve(parameters, {"value": value})


def resolve_cross_section_percentile(
    parameters: Mapping[str, object], value: OnlyCalculationReference
) -> OnlyCalculationDefinition:
    return OnlyOfficialOperatorDefinitionResolver(CROSS_SECTION_PERCENTILE).resolve(parameters, {"value": value})


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    package_root = Path(__file__).resolve().parent
    research_backend = OnlyOfficialResearchOperatorBackend()
    definitions = (ROLLING_MEAN, CROSS_SECTION_PERCENTILE)
    resolvers = {item: OnlyOfficialOperatorDefinitionResolver(item) for item in definitions}
    research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            research_backend,
            resolvers[item],
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
                backend_kind=OnlyCalculationBackendKind.RESEARCH,
                entrypoint_identity="onlyalpha_plugin_operators.research:OnlyOfficialResearchOperatorBackend",
                package_root=package_root,
                resource_paths=("registration.py", "research.py"),
                semantic_dependencies=(
                    only_python_stdlib_semantic_dependency("decimal"),
                    only_distribution_semantic_dependency("pyarrow"),
                ),
            ),
        )
        for item in definitions
    )
    trading = (
        OnlyCalculationBackendRegistration(
            ROLLING_MEAN,
            OnlyCalculationBackendKind.TRADING,
            OnlyOfficialTradingOperatorBackendFactory(),
            resolvers[ROLLING_MEAN],
            only_python_implementation_manifest(
                calculation_type_reference=OnlyCalculationTypeReference(
                    ROLLING_MEAN.kind, ROLLING_MEAN.type_id, ROLLING_MEAN.semantic_version
                ),
                backend_kind=OnlyCalculationBackendKind.TRADING,
                entrypoint_identity="onlyalpha_plugin_operators.trading:OnlyOfficialTradingOperatorBackendFactory",
                package_root=package_root,
                resource_paths=("registration.py", "trading.py"),
                semantic_dependencies=(only_python_stdlib_semantic_dependency("decimal"),),
            ),
            OnlyCalculationStateCapability.CHECKPOINTABLE,
            1,
        ),
    )
    return research + trading
