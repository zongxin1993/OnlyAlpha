"""Pure Indicator declarations and canonical parameter resolvers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.calculation.definition import (
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
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
                "standard_deviations", OnlyParameterType.DECIMAL, False, Decimal(2), Decimal("0.000000000001")
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

_FINANCIAL_NUMERIC = OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "ROUND_HALF_EVEN")
_PRICE = OnlyInputDefinition("price", OnlyCalculationDataType.DECIMAL, True, semantic_type="PRICE")
_VOLUME = OnlyInputDefinition("volume", OnlyCalculationDataType.DECIMAL, True, semantic_type="VOLUME")
_CLOSE = OnlyInputDefinition("close", OnlyCalculationDataType.DECIMAL, True, semantic_type="PRICE")
_HIGH = OnlyInputDefinition("high", OnlyCalculationDataType.DECIMAL, True, semantic_type="PRICE")
_LOW = OnlyInputDefinition("low", OnlyCalculationDataType.DECIMAL, True, semantic_type="PRICE")


def _financial_indicator(
    name: str,
    parameters: tuple[OnlyParameterDefinition, ...],
    inputs: tuple[OnlyInputDefinition, ...],
    outputs: tuple[str, ...],
) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        f"onlyalpha.indicator.{name}",
        "1",
        OnlyParameterSchema(parameters),
        inputs,
        tuple(OnlyOutputDefinition(output, OnlyCalculationDataType.DECIMAL, True) for output in outputs),
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        _FINANCIAL_NUMERIC,
    )


_REQUIRED_PERIOD = (OnlyParameterDefinition("period", OnlyParameterType.INTEGER, True, minimum=1),)
WMA = _financial_indicator("wma", _REQUIRED_PERIOD, (_PRICE,), ("value",))
ROC = _financial_indicator("roc", _REQUIRED_PERIOD, (_PRICE,), ("roc",))
VWAP = _financial_indicator("vwap", _REQUIRED_PERIOD, (_PRICE, _VOLUME), ("vwap",))
OBV = _financial_indicator("obv", (), (_CLOSE, _VOLUME), ("obv",))
STOCHASTIC = _financial_indicator(
    "stochastic",
    (
        OnlyParameterDefinition("k_period", OnlyParameterType.INTEGER, True, minimum=1),
        OnlyParameterDefinition("d_period", OnlyParameterType.INTEGER, False, 3, minimum=1),
    ),
    (_HIGH, _LOW, _CLOSE),
    ("k", "d"),
)
FINANCIAL_TYPES = (WMA, ROC, VWAP, OBV, STOCHASTIC)


# Numerical recalibration creates exact new identities; legacy definitions remain unchanged.
RSI_V2 = replace(TYPES[2], semantic_version="2", numeric=_FINANCIAL_NUMERIC)
ATR_V3 = replace(ATR_V2, semantic_version="3", numeric=_FINANCIAL_NUMERIC)
MACD_V2 = replace(TYPES[8], semantic_version="2", numeric=_FINANCIAL_NUMERIC)
STOCHASTIC_V2 = replace(
    STOCHASTIC,
    semantic_version="2",
    parameters=OnlyParameterSchema(
        (
            OnlyParameterDefinition("k_period", OnlyParameterType.INTEGER, False, 14, minimum=1),
            OnlyParameterDefinition("smooth_k", OnlyParameterType.INTEGER, False, 3, minimum=1),
            OnlyParameterDefinition("d_period", OnlyParameterType.INTEGER, False, 3, minimum=1),
        )
    ),
    missing_values=OnlyMissingValuePolicy.FAIL,
)
VWAP_V2 = replace(
    VWAP,
    semantic_version="2",
    parameters=OnlyParameterSchema(()),
    inputs=(_HIGH, _LOW, _CLOSE, _VOLUME, OnlyInputDefinition("start_ns", OnlyCalculationDataType.INTEGER)),
    missing_values=OnlyMissingValuePolicy.FAIL,
)
CALIBRATED_TYPES = (RSI_V2, ATR_V3, MACD_V2, STOCHASTIC_V2, VWAP_V2)


@dataclass(frozen=True, slots=True)
class OnlyCalibratedDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self, parameters: Mapping[str, object], input_bindings: Mapping[str, OnlyCalculationReference]
    ) -> OnlyCalculationDefinition:
        item = self.type_definition
        p = dict(parameters)
        if item is MACD_V2:
            return resolve_definition(item, p)
        normalized = item.parameters.normalize(p)
        sources = {name: f"bar.{name}" for name in ("high", "low", "close", "volume", "start_ns")}
        sources["value"] = "bar.close" if str(normalized.get("price_field", "CLOSE")) == "CLOSE" else "bar.volume"
        bindings = {i.name: OnlyCalculationReference(None, i.name, sources[i.name]) for i in item.inputs}
        if input_bindings and dict(input_bindings) != bindings:
            raise ValueError("calibrated Indicator inputs conflict with canonical bindings")
        required = int(str(normalized.get("period", 1)))
        if item is RSI_V2:
            required += 1
        elif item is STOCHASTIC_V2:
            required = sum(int(str(normalized[key])) for key in ("k_period", "smooth_k", "d_period")) - 2
        return item.resolve(
            p,
            bindings,
            OnlyWarmupDefinition(
                required, "complete conventional seed/window", OnlyPreReadyOutput.NULL, "FINITE_SERIES"
            ),
        )


@dataclass(frozen=True, slots=True)
class OnlyFinancialIndicatorDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        normalized = self.type_definition.parameters.normalize(parameters)
        defaults = {
            "price": OnlyCalculationReference(None, "price", "bar.close"),
            "volume": OnlyCalculationReference(None, "volume", "bar.volume"),
            "close": OnlyCalculationReference(None, "close", "bar.close"),
            "high": OnlyCalculationReference(None, "high", "bar.high"),
            "low": OnlyCalculationReference(None, "low", "bar.low"),
        }
        bindings = dict(input_bindings) or {item.name: defaults[item.name] for item in self.type_definition.inputs}
        if self.type_definition is ROC:
            observations = int(str(normalized["period"])) + 1
        elif self.type_definition is STOCHASTIC:
            observations = int(str(normalized["k_period"])) + int(str(normalized["d_period"])) - 1
        else:
            observations = int(str(normalized.get("period", 1)))
        return self.type_definition.resolve(
            parameters,
            bindings,
            OnlyWarmupDefinition(
                observations,
                "complete declared financial window is available",
                OnlyPreReadyOutput.NULL,
                "UPSTREAM",
            ),
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
