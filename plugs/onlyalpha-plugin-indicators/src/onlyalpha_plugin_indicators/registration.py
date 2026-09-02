"""Canonical definitions and factories for existing trading Indicators."""
# ruff: noqa: E701

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from onlyalpha.calculation.definition import (
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
    OnlyCalculationImplementationManifest,
    OnlyCalculationStateCapability,
    only_distribution_semantic_dependency,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import (
    ATR,
    BOLLINGER,
    EMA,
    MACD,
    ROLLING_RETURN,
    ROLLING_VOLATILITY,
    RSI,
    SMA,
    ZSCORE,
    OnlyIndicatorId,
    OnlyIndicatorTypeId,
)
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot
from onlyalpha_plugin_indicators.macd import OnlyMacdIndicator, config_from_parameters
from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend
from onlyalpha_plugin_indicators.standard import OnlyRollingIndicatorConfig, OnlyStandardBarIndicator


@dataclass(frozen=True, slots=True)
class OnlyIndicatorBackendRequest:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType


class OnlyStandardBackendFactory:
    def __init__(self, type_definition: OnlyCalculationTypeDefinition) -> None:
        self.type_definition = type_definition

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return _legacy_type(self.type_definition.type_id)

    def resolve_definition(self, parameters: Mapping[str, object]) -> OnlyCalculationDefinition:
        return resolve_definition(self.type_definition, dict(parameters))

    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        if not hasattr(request, "indicator_id") or not hasattr(request, "bar_type"):
            raise TypeError("Indicator backend requires an Indicator request")
        p = definition.parameters
        result = OnlyStandardBarIndicator(
            OnlyRollingIndicatorConfig(
                request.indicator_id,
                request.bar_type,
                int(str(p["period"])),
                str(p["price_field"]),
                Decimal(str(p.get("standard_deviations", "2"))),
            ),
            _legacy_type(definition.type_id),
        )
        result.bind_definition(definition)
        return result


class OnlyMacdBackendFactory:
    def __init__(self, type_definition: OnlyCalculationTypeDefinition) -> None:
        self.type_definition = type_definition

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return MACD

    def resolve_definition(self, parameters: Mapping[str, object]) -> OnlyCalculationDefinition:
        return resolve_definition(self.type_definition, dict(parameters))

    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyMacdIndicator:
        if not hasattr(request, "indicator_id") or not hasattr(request, "bar_type"):
            raise TypeError("Indicator backend requires an Indicator request")
        return OnlyMacdIndicator(
            config_from_parameters(request.indicator_id, request.bar_type, definition.parameters), definition
        )


@dataclass(frozen=True, slots=True)
class OnlyOfficialIndicatorDefinitionResolver:
    """Own complete, backend-neutral semantics for one official Indicator type."""

    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        resolved = resolve_definition(self.type_definition, dict(parameters))
        if input_bindings and dict(input_bindings) != dict(resolved.input_bindings):
            raise ValueError("Indicator template inputs conflict with parameter-derived source bindings")
        return resolved


def _legacy_type(type_id: str) -> OnlyIndicatorTypeId:
    return {
        "onlyalpha.indicator.ema": EMA,
        "onlyalpha.indicator.sma": SMA,
        "onlyalpha.indicator.rsi": RSI,
        "onlyalpha.indicator.atr": ATR,
        "onlyalpha.indicator.bollinger": BOLLINGER,
        "onlyalpha.indicator.rolling_return": ROLLING_RETURN,
        "onlyalpha.indicator.rolling_volatility": ROLLING_VOLATILITY,
        "onlyalpha.indicator.zscore": ZSCORE,
    }[type_id]


def _standard(
    name: str,
    period: int,
    outputs: tuple[OnlyOutputDefinition, ...],
    *,
    extra: tuple[OnlyParameterDefinition, ...] = (),
) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        f"onlyalpha.indicator.{name}",
        "1",
        OnlyParameterSchema(
            (
                OnlyParameterDefinition("period", OnlyParameterType.INTEGER, False, period, 1),
                OnlyParameterDefinition(
                    "price_field",
                    OnlyParameterType.STRING,
                    False,
                    "CLOSE",
                    enum_values=("CLOSE", "VOLUME"),
                    uppercase=True,
                ),
                *extra,
            )
        ),
        (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),),
        outputs,
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(output_quantum=Decimal("0.000000000001")),
    )


VALUE = (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),)
TYPES = (
    _standard("ema", 20, VALUE),
    _standard("sma", 20, VALUE),
    _standard("rsi", 14, (*VALUE, OnlyOutputDefinition("zone", OnlyCalculationDataType.STRING, False))),
    _standard(
        "atr",
        14,
        (
            OnlyOutputDefinition("atr", OnlyCalculationDataType.DECIMAL, True),
            OnlyOutputDefinition("normalized_atr", OnlyCalculationDataType.DECIMAL, True),
        ),
    ),
    _standard(
        "bollinger",
        20,
        (
            OnlyOutputDefinition("middle", OnlyCalculationDataType.DECIMAL, True),
            OnlyOutputDefinition("upper", OnlyCalculationDataType.DECIMAL, True),
            OnlyOutputDefinition("lower", OnlyCalculationDataType.DECIMAL, True),
        ),
        extra=(
            OnlyParameterDefinition(
                "standard_deviations", OnlyParameterType.DECIMAL, False, Decimal("2"), Decimal("0.000000000001")
            ),
        ),
    ),
    _standard("rolling_return", 20, VALUE),
    _standard("rolling_volatility", 20, VALUE),
    _standard("zscore", 20, VALUE),
    OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        "onlyalpha.indicator.macd",
        "1",
        OnlyParameterSchema(
            (
                OnlyParameterDefinition("fast_period", OnlyParameterType.INTEGER, False, 12, 1),
                OnlyParameterDefinition("slow_period", OnlyParameterType.INTEGER, False, 26, 1),
                OnlyParameterDefinition("signal_period", OnlyParameterType.INTEGER, False, 9, 1),
                OnlyParameterDefinition(
                    "price_field", OnlyParameterType.STRING, False, "CLOSE", enum_values=("CLOSE",), uppercase=True
                ),
                OnlyParameterDefinition("warmup_bars", OnlyParameterType.INTEGER, False, 34, 1),
            )
        ),
        (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),),
        (
            OnlyOutputDefinition("dif", OnlyCalculationDataType.DECIMAL, False),
            OnlyOutputDefinition("dea", OnlyCalculationDataType.DECIMAL, False),
            OnlyOutputDefinition("histogram", OnlyCalculationDataType.DECIMAL, False),
            OnlyOutputDefinition("cross_state", OnlyCalculationDataType.STRING, False),
        ),
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(output_quantum=Decimal("0.000000000001")),
    ),
)

ATR_V2 = OnlyCalculationTypeDefinition(
    OnlyCalculationKind.INDICATOR,
    "onlyalpha.indicator.atr",
    "2",
    TYPES[3].parameters,
    (
        OnlyInputDefinition("high", OnlyCalculationDataType.DECIMAL, semantic_type="PRICE"),
        OnlyInputDefinition("low", OnlyCalculationDataType.DECIMAL, semantic_type="PRICE"),
        OnlyInputDefinition("close", OnlyCalculationDataType.DECIMAL, semantic_type="PRICE"),
    ),
    TYPES[3].outputs,
    TYPES[3].missing_values,
    TYPES[3].timestamp,
    TYPES[3].numeric,
)


def warmup(type_definition: OnlyCalculationTypeDefinition, parameters: dict[str, object]) -> OnlyWarmupDefinition:
    normalized = type_definition.parameters.normalize(parameters)
    required = int(str(normalized["warmup_bars"] if "warmup_bars" in normalized else normalized["period"]))
    initialization = "FIRST_VALUE_EMA_SEED" if type_definition.type_id.endswith(("ema", "macd")) else "PARTIAL_WINDOW"
    return OnlyWarmupDefinition(required, "samples >= minimum_observations", OnlyPreReadyOutput.PARTIAL, initialization)


def resolve_definition(
    type_definition: OnlyCalculationTypeDefinition, parameters: dict[str, object]
) -> OnlyCalculationDefinition:
    if type_definition.type_id.endswith(".macd"):
        fast = int(str(parameters.get("fast_period", 12)))
        slow = int(str(parameters.get("slow_period", 26)))
        signal = int(str(parameters.get("signal_period", 9)))
        if fast >= slow:
            raise ValueError("MACD fast_period must be less than slow_period")
        parameters = dict(parameters)
        parameters.setdefault("warmup_bars", slow + signal - 1)
        if int(str(parameters["warmup_bars"])) < slow:
            raise ValueError("MACD warmup_bars cannot be less than slow_period")
    if type_definition is ATR_V2:
        bindings = {name: OnlyCalculationReference(None, name, f"bar.{name}") for name in ("high", "low", "close")}
    else:
        bindings = {
            "value": OnlyCalculationReference(
                None,
                "value",
                "bar.close" if str(parameters.get("price_field", "CLOSE")).upper() == "CLOSE" else "bar.volume",
            )
        }
    return type_definition.resolve(
        parameters,
        bindings,
        warmup(type_definition, parameters),
    )


def registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    resolvers = tuple(OnlyOfficialIndicatorDefinitionResolver(item) for item in (*TYPES, ATR_V2))

    def resolver_for(item: OnlyCalculationTypeDefinition) -> OnlyOfficialIndicatorDefinitionResolver:
        return next(resolver for resolver in resolvers if resolver.type_definition is item)

    package_root = Path(__file__).resolve().parent

    def manifest(
        item: OnlyCalculationTypeDefinition,
        backend: OnlyCalculationBackendKind,
        entrypoint: str,
        resources: tuple[str, ...],
    ) -> OnlyCalculationImplementationManifest:
        return only_python_implementation_manifest(
            calculation_type_reference=OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version),
            backend_kind=backend,
            entrypoint_identity=entrypoint,
            package_root=package_root,
            resource_paths=resources,
            semantic_dependencies=(
                only_python_stdlib_semantic_dependency("decimal"),
                *(
                    (only_distribution_semantic_dependency("pyarrow"),)
                    if backend is OnlyCalculationBackendKind.RESEARCH
                    else ()
                ),
            ),
        )

    trading = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.TRADING,
            OnlyMacdBackendFactory(item) if item.type_id.endswith(".macd") else OnlyStandardBackendFactory(item),
            resolver_for(item),
            manifest(
                item,
                OnlyCalculationBackendKind.TRADING,
                (
                    "onlyalpha_plugin_indicators.registration:OnlyMacdBackendFactory"
                    if item.type_id.endswith(".macd")
                    else "onlyalpha_plugin_indicators.registration:OnlyStandardBackendFactory"
                ),
                (
                    ("registration.py", "macd.py", "snapshots.py")
                    if item.type_id.endswith(".macd")
                    else ("registration.py", "standard.py", "snapshots.py")
                ),
            ),
            OnlyCalculationStateCapability.CHECKPOINTABLE,
            1,
        )
        for item in (*TYPES, ATR_V2)
    )
    research = tuple(
        OnlyCalculationBackendRegistration(
            item,
            OnlyCalculationBackendKind.RESEARCH,
            OnlyOfficialResearchIndicatorBackend(),
            resolver_for(item),
            manifest(
                item,
                OnlyCalculationBackendKind.RESEARCH,
                "onlyalpha_plugin_indicators.research:OnlyOfficialResearchIndicatorBackend",
                ("registration.py", "research.py"),
            ),
        )
        for item in (*TYPES[:3], *TYPES[4:], ATR_V2)
    )
    return trading + research
