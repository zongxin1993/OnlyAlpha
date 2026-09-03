"""Pure Decimal semantics shared by the physical Operator backends."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

from onlyalpha.calculation import OnlyCalculationDefinition, only_decimal_context, only_quantize_decimal


def evaluate(
    definition: OnlyCalculationDefinition, inputs: Mapping[str, Sequence[Decimal | None]]
) -> Mapping[str, tuple[Decimal | None, ...]]:
    names = {item.name for item in definition.inputs}
    if set(inputs) != names:
        raise ValueError(f"Operator input names must be {sorted(names)}")
    inputs = {name: tuple(values) for name, values in inputs.items()}
    lengths = {len(values) for values in inputs.values()}
    if len(lengths) != 1:
        raise ValueError("Operator input lengths differ")
    if any(
        value is not None and (not isinstance(value, Decimal) or not value.is_finite())
        for column in inputs.values()
        for value in column
    ):
        raise ValueError("Operator inputs must be finite Decimal or null")
    name = definition.type_id.removeprefix("onlyalpha.operator.")
    with localcontext(only_decimal_context(definition.numeric)):
        if name.startswith("cross_section_"):
            return {_output_name(definition): _cross_section(definition, tuple(inputs["value"]))}
        size = next(iter(lengths), 0)
        return {_output_name(definition): tuple(_at(definition, inputs, index) for index in range(size))}


def _at(
    definition: OnlyCalculationDefinition, inputs: Mapping[str, Sequence[Decimal | None]], index: int
) -> Decimal | None:
    name = definition.type_id.removeprefix("onlyalpha.operator.")
    if name in {"add", "subtract", "multiply", "divide"}:
        left, right = inputs["left"][index], inputs["right"][index]
        if left is None or right is None or (name == "divide" and right == 0):
            return None
        if name == "add":
            result = left + right
        elif name == "subtract":
            result = left - right
        elif name == "multiply":
            result = left * right
        else:
            result = left / right
        return _q(definition, result)
    value = inputs.get("value", (None,) * (index + 1))[index]
    if name in {"abs", "sign", "log", "scale"}:
        if value is None or (name == "log" and value <= 0):
            return None
        if name == "abs":
            result = abs(value)
        elif name == "sign":
            result = Decimal(1 if value > 0 else -1 if value < 0 else 0)
        elif name == "log":
            result = value.ln()
        else:
            result = value * Decimal(str(definition.parameters["factor"]))
        return _q(definition, result)
    period = int(str(definition.parameters["period"]))
    if name in {"delay", "delta"}:
        if index < period or value is None or inputs["value"][index - period] is None:
            return None
        delayed = inputs["value"][index - period]
        assert delayed is not None
        return _q(definition, delayed if name == "delay" else value - delayed)
    start = index - period + 1
    if start < 0:
        return None
    if name in {"rolling_covariance", "rolling_correlation"}:
        left_window = tuple(inputs["left"][start : index + 1])
        right_window = tuple(inputs["right"][start : index + 1])
        if any(item is None for item in (*left_window, *right_window)):
            return None
        x = tuple(item for item in left_window if item is not None)
        y = tuple(item for item in right_window if item is not None)
        mx, my = _mean(x), _mean(y)
        covariance = sum(((a - mx) * (b - my) for a, b in zip(x, y, strict=True)), Decimal(0)) / Decimal(period)
        if name == "rolling_covariance":
            return _q(definition, covariance)
        vx, vy = _variance(x, mx), _variance(y, my)
        if vx == 0 or vy == 0:
            return None
        return _q(definition, covariance / (vx * vy).sqrt())
    window = tuple(inputs["value"][start : index + 1])
    if any(item is None for item in window):
        return None
    exact = tuple(item for item in window if item is not None)
    if name == "rolling_sum":
        result = sum(exact, Decimal(0))
    elif name == "rolling_mean":
        result = _mean(exact)
    elif name in {"rolling_var", "rolling_std"}:
        result = _variance(exact, _mean(exact))
        if name == "rolling_std":
            result = result.sqrt()
    elif name == "rolling_min":
        result = min(exact)
    elif name == "rolling_max":
        result = max(exact)
    elif name == "ts_rank":
        return _q(definition, _rank(exact, exact[-1]))
    elif name == "decay_linear":
        result = sum((item * Decimal(weight) for weight, item in enumerate(exact, 1)), Decimal(0)) / Decimal(
            period * (period + 1) // 2
        )
    else:
        raise ValueError(f"unsupported official Operator: {definition.type_id}@{definition.semantic_version}")
    return _q(definition, result)


def _cross_section(
    definition: OnlyCalculationDefinition, values: tuple[Decimal | None, ...]
) -> tuple[Decimal | None, ...]:
    name = definition.type_id.removeprefix("onlyalpha.operator.cross_section_")
    eligible = tuple(sorted(value for value in values if value is not None))
    if name in {"percentile", "rank"}:
        if name == "percentile" and definition.parameters["tie_method"] != "AVERAGE":
            raise ValueError("Cross-section percentile requires AVERAGE tie_method")
        scores = {value: _rank(eligible, value) for value in eligible}
        if name == "percentile" and definition.parameters["direction"] == "LOWER_IS_BETTER":
            scores = {value: Decimal(1) - score for value, score in scores.items()}
        return tuple(None if value is None else _q(definition, scores[value]) for value in values)
    if not eligible:
        return tuple(None for _ in values)
    mean = _mean(eligible)
    if name == "demean":
        return tuple(None if value is None else _q(definition, value - mean) for value in values)
    if name == "zscore":
        variance = _variance(eligible, mean)
        if variance == 0:
            return tuple(None for _ in values)
        std = variance.sqrt()
        return tuple(None if value is None else _q(definition, (value - mean) / std) for value in values)
    raise ValueError(f"unsupported cross-section Operator: {definition.type_id}")


def _rank(values: tuple[Decimal, ...], target: Decimal) -> Decimal:
    if len(values) == 1:
        return Decimal("0.5")
    low = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    return (Decimal(low) + Decimal(equal - 1) / 2) / Decimal(len(values) - 1)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _variance(values: tuple[Decimal, ...], mean: Decimal) -> Decimal:
    return sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(len(values))


def _output_name(definition: OnlyCalculationDefinition) -> str:
    return definition.outputs[0].name


def _q(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("Operator requires output_quantum")
    return only_quantize_decimal(definition.numeric, value)
