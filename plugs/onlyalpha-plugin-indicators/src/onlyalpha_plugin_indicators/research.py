"""Exact Decimal finite-series RESEARCH Indicator backends."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDefinition, OnlyMissingValuePolicy
from onlyalpha_plugin_indicators.financial_semantics import evaluate_financial

_Q = Decimal("0.000000000001")
_DECIMAL = pa.decimal128(38, 12)


class OnlyOfficialResearchIndicatorBackend:
    """Columnar batch adapter around independent deterministic Decimal kernels."""

    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if definition.type_id in {
            "onlyalpha.indicator.wma",
            "onlyalpha.indicator.roc",
            "onlyalpha.indicator.vwap",
            "onlyalpha.indicator.obv",
            "onlyalpha.indicator.stochastic",
        }:
            if any(not pa.types.is_decimal(array.type) for array in inputs.values()):
                raise ValueError("B1 financial Indicator inputs must use Arrow Decimal")
            result = evaluate_financial(definition, {name: tuple(array.to_pylist()) for name, array in inputs.items()})
            return {name: _decimal_array(values) for name, values in result.items()}
        if definition.missing_values is not OnlyMissingValuePolicy.FAIL:
            raise ValueError("official RESEARCH Indicators require missing-value FAIL")
        values = {name: tuple(array.to_pylist()) for name, array in inputs.items()}
        if any(item is None for column in values.values() for item in column):
            raise ValueError("missing input is forbidden")
        lengths = {len(column) for column in values.values()}
        if len(lengths) != 1:
            raise ValueError("input lengths differ")
        kind = definition.type_id.rsplit(".", 1)[-1]
        if kind == "macd":
            return _macd(definition, _decimals(values["value"]))
        if kind == "atr":
            if definition.semantic_version != "2":
                raise ValueError("atr@1 has no RESEARCH backend because its declared inputs are incomplete")
            return _atr(
                definition,
                _decimals(values["high"]),
                _decimals(values["low"]),
                _decimals(values["close"]),
            )
        return _standard(definition, _decimals(values["value"]))


def _standard(definition: OnlyCalculationDefinition, values: tuple[Decimal, ...]) -> Mapping[str, pa.Array]:
    period = int(str(definition.parameters["period"]))
    kind = definition.type_id.rsplit(".", 1)[-1]
    window: deque[Decimal] = deque(maxlen=period + 1)
    output: list[Decimal | None] = []
    zones: list[str] = []
    ema: Decimal | None = None
    for value in values:
        window.append(value)
        current = tuple(window)
        if kind == "ema":
            alpha = Decimal(2) / Decimal(period + 1)
            ema = value if ema is None else ema + alpha * (value - ema)
            result = ema
        elif kind == "sma":
            result = _mean(current[-period:])
        elif kind == "rsi":
            result = None
            if len(current) >= 2:
                changes = tuple(right - left for left, right in zip(current, current[1:], strict=False))[-period:]
                gain = sum((max(item, Decimal(0)) for item in changes), Decimal(0)) / Decimal(len(changes))
                loss = sum((max(-item, Decimal(0)) for item in changes), Decimal(0)) / Decimal(len(changes))
                result = Decimal(100) if loss == 0 else Decimal(100) - Decimal(100) / (Decimal(1) + gain / loss)
            zones.append(
                "NEUTRAL"
                if result is None or Decimal(30) <= result <= Decimal(70)
                else ("OVERSOLD" if result < 30 else "OVERBOUGHT")
            )
        elif kind == "bollinger":
            current_window = current[-period:]
            mean = _mean(current_window)
            deviation = _std(current_window, mean)
            width = deviation * Decimal(str(definition.parameters["standard_deviations"]))
            # The multi-output path is assembled after the loop.
            output.append(_q(mean))
            zones.extend((str(_q(mean + width)), str(_q(mean - width))))
            continue
        elif kind == "rolling_return":
            result = (
                None if len(current) <= period or current[-period - 1] == 0 else current[-1] / current[-period - 1] - 1
            )
        elif kind == "rolling_volatility":
            current_window = current[-period:]
            result = _std(current_window, _mean(current_window))
        elif kind == "zscore":
            current_window = current[-period:]
            mean = _mean(current_window)
            std = _std(current_window, mean)
            result = Decimal(0) if std == 0 else (value - mean) / std
        else:
            raise ValueError(f"unsupported official Indicator: {kind}")
        output.append(_q(result))
    if kind == "rsi":
        return {"value": _decimal_array(output), "zone": pa.array(zones, type=pa.string())}
    if kind == "bollinger":
        upper = [Decimal(zones[index]) for index in range(0, len(zones), 2)]
        lower = [Decimal(zones[index]) for index in range(1, len(zones), 2)]
        return {"middle": _decimal_array(output), "upper": _decimal_array(upper), "lower": _decimal_array(lower)}
    return {"value": _decimal_array(output)}


def _atr(
    definition: OnlyCalculationDefinition,
    highs: tuple[Decimal, ...],
    lows: tuple[Decimal, ...],
    closes: tuple[Decimal, ...],
) -> Mapping[str, pa.Array]:
    period = int(str(definition.parameters["period"]))
    ranges: deque[Decimal] = deque(maxlen=period)
    atrs: list[Decimal | None] = []
    normalized: list[Decimal | None] = []
    previous: Decimal | None = None
    for high, low, close in zip(highs, lows, closes, strict=True):
        true_range = high - low
        if previous is not None:
            true_range = max(true_range, abs(high - previous), abs(low - previous))
        ranges.append(true_range)
        atr = _mean(tuple(ranges))
        atrs.append(_q(atr))
        normalized.append(None if close == 0 else _q(atr / close))
        previous = close
    return {"atr": _decimal_array(atrs), "normalized_atr": _decimal_array(normalized)}


def _macd(definition: OnlyCalculationDefinition, values: tuple[Decimal, ...]) -> Mapping[str, pa.Array]:
    fast_period = int(str(definition.parameters["fast_period"]))
    slow_period = int(str(definition.parameters["slow_period"]))
    signal_period = int(str(definition.parameters["signal_period"]))
    fast_alpha = Decimal(2) / Decimal(fast_period + 1)
    slow_alpha = Decimal(2) / Decimal(slow_period + 1)
    signal_alpha = Decimal(2) / Decimal(signal_period + 1)
    fast: Decimal | None = None
    slow: Decimal | None = None
    dea_state: Decimal | None = None
    previous_dif = Decimal(0)
    previous_dea = Decimal(0)
    difs: list[Decimal] = []
    deas: list[Decimal] = []
    histograms: list[Decimal] = []
    crosses: list[str] = []
    for index, price in enumerate(values):
        fast = price if fast is None else fast + fast_alpha * (price - fast)
        slow = price if slow is None else slow + slow_alpha * (price - slow)
        dif = _quantize(fast - slow)
        dea_state = dif if dea_state is None else dea_state + signal_alpha * (dif - dea_state)
        dea = _quantize(dea_state)
        delta = dif - dea
        previous_delta = previous_dif - previous_dea
        cross = "NONE"
        if index > 0 and previous_delta <= 0 < delta:
            cross = "GOLDEN_CROSS"
        elif index > 0 and previous_delta >= 0 > delta:
            cross = "DEATH_CROSS"
        difs.append(dif)
        deas.append(dea)
        histograms.append(_quantize(delta * Decimal(2)))
        crosses.append(cross)
        previous_dif, previous_dea = dif, dea
    return {
        "dif": _decimal_array(difs),
        "dea": _decimal_array(deas),
        "histogram": _decimal_array(histograms),
        "cross_state": pa.array(crosses, type=pa.string()),
    }


def _decimals(values: tuple[object, ...]) -> tuple[Decimal, ...]:
    if any(not isinstance(value, Decimal) for value in values):
        raise ValueError("official Indicator inputs must be Decimal")
    return tuple(value for value in values if isinstance(value, Decimal))


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return Decimal(0) if not values else sum(values, Decimal(0)) / Decimal(len(values))


def _std(values: tuple[Decimal, ...], mean: Decimal) -> Decimal:
    if not values:
        return Decimal(0)
    with localcontext() as context:
        context.prec = 28
        return (sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(len(values))).sqrt()


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_Q)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_Q)


def _decimal_array(values: Sequence[Decimal | None]) -> pa.Array:
    return pa.array(values, type=_DECIMAL)
