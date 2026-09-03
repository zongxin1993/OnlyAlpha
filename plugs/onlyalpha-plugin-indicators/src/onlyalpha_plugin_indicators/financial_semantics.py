"""Pure Decimal semantics for the B1 financial feature family."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal, localcontext

from onlyalpha.calculation import OnlyCalculationDefinition


@contextmanager
def financial_numeric_context(definition: OnlyCalculationDefinition) -> Iterator[None]:
    with localcontext() as context:
        context.prec, context.rounding = definition.numeric.precision, definition.numeric.rounding
        yield


def quantize_financial(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("financial Indicator requires output_quantum")
    with financial_numeric_context(definition):
        return value.quantize(quantum)


def evaluate_financial(
    definition: OnlyCalculationDefinition,
    inputs: Mapping[str, Sequence[Decimal | None]],
) -> Mapping[str, tuple[Decimal | None, ...]]:
    expected = {item.name for item in definition.inputs}
    if set(inputs) != expected:
        raise ValueError(f"financial Indicator input names must be {sorted(expected)}")
    columns = {name: tuple(values) for name, values in inputs.items()}
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1:
        raise ValueError("financial Indicator input lengths differ")
    if any(
        value is not None and (not isinstance(value, Decimal) or not value.is_finite())
        for column in columns.values()
        for value in column
    ):
        raise ValueError("financial Indicator inputs must be finite Decimal or null")
    name = definition.type_id.removeprefix("onlyalpha.indicator.")
    size = next(iter(lengths), 0)
    with financial_numeric_context(definition):
        if name == "stochastic":
            return _stochastic(definition, columns, size)
        if name == "obv":
            return {"obv": _obv(definition, columns, size)}
        values = tuple(_at(definition, columns, index) for index in range(size))
        return {definition.outputs[0].name: values}


def _at(
    definition: OnlyCalculationDefinition, inputs: Mapping[str, tuple[Decimal | None, ...]], index: int
) -> Decimal | None:
    name = definition.type_id.removeprefix("onlyalpha.indicator.")
    period = int(str(definition.parameters["period"]))
    if name == "roc":
        price = inputs["price"]
        if index < period or price[index] is None or price[index - period] in {None, Decimal(0)}:
            return None
        return _q(definition, price[index] / price[index - period] - 1)  # type: ignore[operator]
    start = index - period + 1
    if start < 0:
        return None
    if name == "wma":
        window = inputs["price"][start : index + 1]
        if any(value is None for value in window):
            return None
        total = Decimal(period * (period + 1) // 2)
        return _q(
            definition,
            sum((value * weight for weight, value in enumerate(window, 1) if value is not None), Decimal(0)) / total,
        )
    if name == "vwap":
        prices, volumes = inputs["price"][start : index + 1], inputs["volume"][start : index + 1]
        if any(value is None for value in (*prices, *volumes)):
            return None
        aggregate_volume = sum((value for value in volumes if value is not None), Decimal(0))
        if aggregate_volume == 0:
            return None
        weighted = sum(
            (
                price * quantity
                for price, quantity in zip(prices, volumes, strict=True)
                if price is not None and quantity is not None
            ),
            Decimal(0),
        )
        return _q(definition, weighted / aggregate_volume)
    raise ValueError(f"unsupported B1 financial Indicator: {definition.type_id}")


def _obv(
    definition: OnlyCalculationDefinition,
    inputs: Mapping[str, tuple[Decimal | None, ...]],
    size: int,
) -> tuple[Decimal | None, ...]:
    close_values, volume_values = inputs["close"], inputs["volume"]
    result: list[Decimal | None] = []
    total = Decimal(0)
    valid = True
    previous: Decimal | None = None
    for index in range(size):
        current, quantity = close_values[index], volume_values[index]
        if current is None or quantity is None or (previous is None and index > 0):
            valid = False
        if valid and previous is not None and current is not None and quantity is not None:
            if current > previous:
                total += quantity
            elif current < previous:
                total -= quantity
        result.append(_q(definition, total) if valid else None)
        previous = current
    return tuple(result)


def _stochastic(
    definition: OnlyCalculationDefinition, inputs: Mapping[str, tuple[Decimal | None, ...]], size: int
) -> Mapping[str, tuple[Decimal | None, ...]]:
    k_period = int(str(definition.parameters["k_period"]))
    d_period = int(str(definition.parameters["d_period"]))
    ks: list[Decimal | None] = []
    for index in range(size):
        start = index - k_period + 1
        if start < 0:
            ks.append(None)
            continue
        highs, lows = inputs["high"][start : index + 1], inputs["low"][start : index + 1]
        close = inputs["close"][index]
        if close is None or any(value is None for value in (*highs, *lows)):
            ks.append(None)
            continue
        high = max(value for value in highs if value is not None)
        low = min(value for value in lows if value is not None)
        ks.append(None if high == low else _q(definition, (close - low) / (high - low) * Decimal(100)))
    ds: list[Decimal | None] = []
    for index in range(size):
        window = ks[index - d_period + 1 : index + 1]
        ds.append(
            None
            if len(window) < d_period or any(value is None for value in window)
            else _q(definition, sum((value for value in window if value is not None), Decimal(0)) / Decimal(d_period))
        )
    return {"k": tuple(ks), "d": tuple(ds)}


def _q(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    return quantize_financial(definition, value)
