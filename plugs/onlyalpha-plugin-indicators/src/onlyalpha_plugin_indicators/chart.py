"""Exact registration support and backend-owned point quality for transient studies."""

from collections.abc import Mapping
from typing import Literal

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.algorithm.batch import OnlyResearchCalculationBackendExecutionV2, OnlyResearchOutputReadiness
from onlyalpha.calculation import OnlyCalculationDefinition, OnlyCalculationTypeDefinition
from onlyalpha.calculation.chart_study import OnlyChartStudySeries, OnlyChartStudySupport

# Conservative operation upper bound for this plugin's finite-series chart kernels.
CHART_STUDY_MAX_WORK_UNITS = 5_000_000


def require_chart_capacity(definition: OnlyCalculationDefinition, row_count: int) -> None:
    if type(row_count) is not int or row_count < 0:
        raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")
    parameters = definition.parameters
    name = definition.type_id.rsplit(".", 1)[-1]
    if name == "stochastic":
        per_row = int(str(parameters["k_period"])) * (
            int(str(parameters.get("smooth_k", 1))) + int(str(parameters["d_period"]))
        )
    else:
        per_row = int(str(parameters.get("period", 1)))
    if row_count * per_row > CHART_STUDY_MAX_WORK_UNITS:
        raise ValueError("CHART_STUDY_CAPACITY_EXCEEDED")


def chart_support(item: OnlyCalculationTypeDefinition) -> OnlyChartStudySupport | None:
    from onlyalpha_plugin_indicators.definitions import ATR_V2, CALIBRATED_TYPES, FINANCIAL_TYPES, TYPES

    admitted = (*TYPES[:3], *TYPES[4:], ATR_V2, *FINANCIAL_TYPES, *CALIBRATED_TYPES)
    if item not in admitted:
        return None
    name = item.type_id.rsplit(".", 1)[-1]
    defaults: dict[str, object] = {}
    labels = {
        "ema": "EMA",
        "sma": "SMA",
        "rsi": "RSI · Wilder",
        "atr": "ATR · Wilder",
        "bollinger": "布林带",
        "rolling_return": "滚动收益率",
        "rolling_volatility": "价格波动率",
        "zscore": "Z-Score",
        "macd": "MACD",
        "wma": "WMA",
        "roc": "ROC",
        "vwap": "VWAP · UTC交易日",
        "obv": "OBV",
        "stochastic": "Stochastic · 慢速",
    }
    if name in {"wma", "roc"} or (name == "vwap" and item.semantic_version == "1"):
        defaults["period"] = 20
    if name == "stochastic" and item.semantic_version == "1":
        defaults["k_period"] = 14
    overlay = name in {"ema", "sma", "wma", "bollinger", "vwap"}
    units: dict[str, Literal["PRICE", "RATIO", "VOLUME", "SCALAR"]] = {
        "ema": "PRICE",
        "sma": "PRICE",
        "wma": "PRICE",
        "bollinger": "PRICE",
        "vwap": "PRICE",
        "atr": "PRICE",
        "macd": "PRICE",
        "rolling_volatility": "PRICE",
        "rolling_return": "RATIO",
        "roc": "RATIO",
        "rsi": "SCALAR",
        "stochastic": "SCALAR",
        "zscore": "SCALAR",
        "obv": "VOLUME",
    }
    defaults = {
        key: str(value) if hasattr(value, "as_tuple") else value
        for key, value in item.parameters.normalize(defaults).items()
    }
    default_variant = not (
        (name in {"rsi", "macd", "stochastic", "vwap"} and item.semantic_version == "1")
        or (name == "atr" and item.semantic_version == "2")
    )
    if not default_variant:
        labels[name] = {
            "rsi": "RSI · 原始滚动均值",
            "atr": "ATR · 原始滚动均值",
            "macd": "MACD · 原始双倍柱",
            "stochastic": "Stochastic · 原始快速",
            "vwap": "VWAP · 原始滚动",
        }[name]
    colors = ("#2962ff", "#f59e0b", "#14b8a6")
    series = tuple(
        OnlyChartStudySeries(
            output.name,
            output.name.upper() if name in {"macd", "stochastic"} else labels[name],
            "HISTOGRAM" if output.name == "histogram" else "LINE",
            units[name],
            colors[index % len(colors)],
        )
        for index, output in enumerate(item.outputs)
        if output.name not in {"zone", "cross_state", "normalized_atr"}
    )
    return OnlyChartStudySupport(
        labels[name],
        "趋势" if overlay else "动量 / 波动",
        defaults,
        series,
        "PRICE_OVERLAY" if overlay else "SEPARATE_PANE",
        ("upper", "lower") if name == "bollinger" else None,
        default_variant=default_variant,
    )


def chart_execution(
    definition: OnlyCalculationDefinition,
    inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    outputs: Mapping[str, pa.Array | pa.ChunkedArray],
) -> OnlyResearchCalculationBackendExecutionV2:
    """Produce quality from this kernel's declared finite-series state, never UI inference."""
    name = definition.type_id.rsplit(".", 1)[-1]
    period = int(str(definition.parameters.get("period", 1)))
    required = definition.warmup.minimum_observations
    if name in {"rolling_return", "roc"}:
        required = period + 1
    readiness = {}
    columns = {key: value.to_pylist() for key, value in inputs.items()}
    for output_name, values in outputs.items():
        states, reasons = [], []
        output_required = required
        if name == "stochastic" and output_name == "k":
            output_required = (
                int(str(definition.parameters["k_period"])) + int(str(definition.parameters.get("smooth_k", 1))) - 1
            )
        for index, value in enumerate(values.to_pylist()):
            # PROPAGATE financial windows distinguish absent inputs from undefined valid zero-denominators.
            if name in {"wma", "roc", "obv", "vwap", "stochastic"} and value is None:
                window = period + 1 if name == "roc" else period
                if name == "stochastic":
                    window = int(str(definition.parameters["k_period"])) + (
                        int(str(definition.parameters["d_period"])) - 1 if output_name == "d" else 0
                    )
                start = 0 if name == "obv" else max(0, index - window + 1)
                missing = any(v is None for column in columns.values() for v in column[start : index + 1])
            else:
                missing = False
            if missing:
                state, reason = "UNAVAILABLE", "INPUT_UNAVAILABLE"
            elif index + 1 < output_required:
                state, reason = "PARTIAL", "WARMUP_INCOMPLETE"
            else:
                state, reason = "READY", "VALUE_UNDEFINED" if value is None else "NONE"
            states.append(state)
            reasons.append(reason)
        readiness[output_name] = OnlyResearchOutputReadiness(
            pa.array(states, type=pa.string()), pa.array(reasons, type=pa.string())
        )
    return OnlyResearchCalculationBackendExecutionV2(outputs, readiness)
