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
    only_decimal_execution_semantic_dependency,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationStateCapability,
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha_plugin_operators.research import OnlyOfficialResearchOperatorBackend
from onlyalpha_plugin_operators.trading import OnlyOfficialTradingOperatorBackendFactory

_NUMERIC = OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
_VALUE_INPUT = (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, True),)
_BINARY_INPUTS = (
    OnlyInputDefinition("left", OnlyCalculationDataType.DECIMAL, True),
    OnlyInputDefinition("right", OnlyCalculationDataType.DECIMAL, True),
)
_PERIOD = OnlyParameterSchema((OnlyParameterDefinition("period", OnlyParameterType.INTEGER, True, minimum=1),))
_NONE = OnlyParameterSchema()


def _type(
    name: str,
    *,
    parameters: OnlyParameterSchema = _NONE,
    inputs: tuple[OnlyInputDefinition, ...] = _VALUE_INPUT,
    output: str = "value",
    shape: OnlyFactorKind = OnlyFactorKind.TIME_SERIES,
) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        f"onlyalpha.operator.{name}",
        "1",
        parameters,
        inputs,
        (OnlyOutputDefinition(output, OnlyCalculationDataType.DECIMAL, True),),
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        _NUMERIC,
        execution_shape=shape,
    )


ADD = _type("add", inputs=_BINARY_INPUTS)
SUBTRACT = _type("subtract", inputs=_BINARY_INPUTS)
MULTIPLY = _type("multiply", inputs=_BINARY_INPUTS)
DIVIDE = _type("divide", inputs=_BINARY_INPUTS)
ABS = _type("abs")
SIGN = _type("sign")
LOG = _type("log")
DELAY = _type("delay", parameters=_PERIOD)
DELTA = _type("delta", parameters=_PERIOD)
ROLLING_MEAN = _type("rolling_mean", parameters=_PERIOD)
ROLLING_SUM = _type("rolling_sum", parameters=_PERIOD)
ROLLING_STD = _type("rolling_std", parameters=_PERIOD)
ROLLING_VAR = _type("rolling_var", parameters=_PERIOD)
ROLLING_MIN = _type("rolling_min", parameters=_PERIOD)
ROLLING_MAX = _type("rolling_max", parameters=_PERIOD)
ROLLING_COVARIANCE = _type("rolling_covariance", parameters=_PERIOD, inputs=_BINARY_INPUTS)
ROLLING_CORRELATION = _type("rolling_correlation", parameters=_PERIOD, inputs=_BINARY_INPUTS)
TS_RANK = _type("ts_rank", parameters=_PERIOD)
SCALE = _type(
    "scale",
    parameters=OnlyParameterSchema(
        (OnlyParameterDefinition("factor", OnlyParameterType.DECIMAL, False, Decimal("1")),)
    ),
)
DECAY_LINEAR = _type("decay_linear", parameters=_PERIOD)
CROSS_SECTION_PERCENTILE = _type(
    "cross_section_percentile",
    parameters=OnlyParameterSchema(
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
    output="percentile",
    shape=OnlyFactorKind.CROSS_SECTION,
)
CROSS_SECTION_RANK = _type("cross_section_rank", output="rank", shape=OnlyFactorKind.CROSS_SECTION)
CROSS_SECTION_ZSCORE = _type("cross_section_zscore", output="zscore", shape=OnlyFactorKind.CROSS_SECTION)
CROSS_SECTION_DEMEAN = _type("cross_section_demean", output="demeaned", shape=OnlyFactorKind.CROSS_SECTION)

P0_TYPES = (
    ADD,
    SUBTRACT,
    MULTIPLY,
    DIVIDE,
    ABS,
    SIGN,
    LOG,
    DELAY,
    DELTA,
    ROLLING_MEAN,
    ROLLING_SUM,
    ROLLING_STD,
    ROLLING_VAR,
    ROLLING_MIN,
    ROLLING_MAX,
    ROLLING_COVARIANCE,
    ROLLING_CORRELATION,
    TS_RANK,
    SCALE,
    DECAY_LINEAR,
    CROSS_SECTION_PERCENTILE,
    CROSS_SECTION_RANK,
    CROSS_SECTION_ZSCORE,
    CROSS_SECTION_DEMEAN,
)
_STATELESS = frozenset({ADD, SUBTRACT, MULTIPLY, DIVIDE, ABS, SIGN, LOG, SCALE})
_CROSS_SECTION = frozenset(
    {
        CROSS_SECTION_PERCENTILE,
        CROSS_SECTION_RANK,
        CROSS_SECTION_ZSCORE,
        CROSS_SECTION_DEMEAN,
    }
)


def _warmup_for(
    type_definition: OnlyCalculationTypeDefinition,
    normalized_parameters: Mapping[str, object],
) -> OnlyWarmupDefinition:
    period = int(str(normalized_parameters.get("period", 1)))
    if type_definition in {ROLLING_MEAN, CROSS_SECTION_PERCENTILE}:
        return OnlyWarmupDefinition(
            period,
            "complete declared input window is available" if period > 1 else "declared input is available",
            OnlyPreReadyOutput.NULL,
            "UPSTREAM",
        )
    observations = period + 1 if type_definition in {DELAY, DELTA} else period
    return OnlyWarmupDefinition(
        observations,
        "complete inclusive declared window is available" if observations > 1 else "declared inputs are available",
        OnlyPreReadyOutput.NULL,
        "UPSTREAM",
    )


@dataclass(frozen=True, slots=True)
class OnlyOfficialOperatorDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self, parameters: Mapping[str, object], input_bindings: Mapping[str, OnlyCalculationReference]
    ) -> OnlyCalculationDefinition:
        normalized = self.type_definition.parameters.normalize(parameters)
        return self.type_definition.resolve(
            parameters,
            input_bindings,
            _warmup_for(self.type_definition, normalized),
        )


def resolve_operator(
    type_definition: OnlyCalculationTypeDefinition,
    parameters: Mapping[str, object],
    **input_bindings: OnlyCalculationReference,
) -> OnlyCalculationDefinition:
    return OnlyOfficialOperatorDefinitionResolver(type_definition).resolve(parameters, input_bindings)


def resolve_rolling_mean(
    parameters: Mapping[str, object], value: OnlyCalculationReference
) -> OnlyCalculationDefinition:
    return resolve_operator(ROLLING_MEAN, parameters, value=value)


def resolve_cross_section_percentile(
    parameters: Mapping[str, object], value: OnlyCalculationReference
) -> OnlyCalculationDefinition:
    return resolve_operator(CROSS_SECTION_PERCENTILE, parameters, value=value)


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    package_root = Path(__file__).resolve().parent
    research_backend = OnlyOfficialResearchOperatorBackend()
    resolvers = {item: OnlyOfficialOperatorDefinitionResolver(item) for item in P0_TYPES}

    def manifest(
        item: OnlyCalculationTypeDefinition, backend: OnlyCalculationBackendKind
    ) -> OnlyCalculationImplementationManifest:
        module = "research" if backend is OnlyCalculationBackendKind.RESEARCH else "trading"
        dependencies = [
            only_decimal_execution_semantic_dependency(),
            only_python_stdlib_semantic_dependency("decimal"),
        ]
        if backend is OnlyCalculationBackendKind.RESEARCH:
            dependencies.append(only_distribution_semantic_dependency("pyarrow"))
        return only_python_implementation_manifest(
            calculation_type_reference=OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
            backend_kind=backend,
            entrypoint_identity=(
                "onlyalpha_plugin_operators.research:OnlyOfficialResearchOperatorBackend"
                if backend is OnlyCalculationBackendKind.RESEARCH
                else "onlyalpha_plugin_operators.trading:OnlyOfficialTradingOperatorBackendFactory"
            ),
            package_root=package_root,
            resource_paths=("registration.py", "semantics.py", f"{module}.py"),
            semantic_dependencies=tuple(dependencies),
        )

    research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            research_backend,
            resolvers[item],
            manifest(item, OnlyCalculationBackendKind.RESEARCH),
        )
        for item in P0_TYPES
    )
    trading = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.TRADING,
            OnlyOfficialTradingOperatorBackendFactory(),
            resolvers[item],
            manifest(item, OnlyCalculationBackendKind.TRADING),
            OnlyCalculationStateCapability.STATELESS
            if item in _STATELESS
            else OnlyCalculationStateCapability.CHECKPOINTABLE,
            None if item in _STATELESS else (2 if item is ROLLING_MEAN else 1),
        )
        for item in P0_TYPES
        if item not in _CROSS_SECTION
    )
    return research + trading


__all__ = [name for name in globals() if name.isupper() or name.startswith(("Only", "resolve_", "registrations"))]
