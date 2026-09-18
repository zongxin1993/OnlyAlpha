"""Exact incremental TRADING backend for the example Momentum hypothesis."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext

from onlyalpha.calculation import OnlyCalculationDefinition


class OnlyExampleTradingMomentumBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        if definition.type_id != "example.factor.momentum" or definition.semantic_version != "1":
            raise ValueError(f"unsupported example TRADING Factor: {definition.type_id}@{definition.semantic_version}")
        return OnlyExampleTradingMomentumBackend(definition)


@dataclass(frozen=True, slots=True)
class OnlyExampleTradingMomentumBackend:
    definition: OnlyCalculationDefinition

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        if set(inputs) != {"return_short", "return_long"}:
            raise ValueError("Momentum TRADING inputs are invalid")
        short = inputs["return_short"]
        long = inputs["return_long"]
        if short is None or long is None:
            return {"factor_value": None}
        if not isinstance(short, Decimal) or not isinstance(long, Decimal):
            raise TypeError("Momentum TRADING inputs must be Decimal or null")
        short_weight = self.definition.parameters["short_weight"]
        long_weight = self.definition.parameters["long_weight"]
        if not isinstance(short_weight, Decimal) or not isinstance(long_weight, Decimal):
            raise TypeError("Momentum weights must be Decimal")
        quantum = self.definition.numeric.output_quantum
        if quantum is None:
            raise ValueError("Momentum requires an output quantum")
        with localcontext() as context:
            context.prec = self.definition.numeric.precision
            context.rounding = self.definition.numeric.rounding
            value = (short_weight * short + long_weight * long).quantize(quantum)
        return {"factor_value": value}


__all__ = [name for name in globals() if name.startswith("Only")]
