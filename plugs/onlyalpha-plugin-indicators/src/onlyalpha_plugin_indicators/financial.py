"""Checkpointable incremental TRADING backend for B1 financial features."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from onlyalpha.calculation import OnlyCalculationDefinition
from onlyalpha_plugin_indicators.financial_semantics import evaluate_financial


class OnlyFinancialTradingBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        if definition.semantic_version != "1" or definition.type_id not in {
            "onlyalpha.indicator.wma",
            "onlyalpha.indicator.roc",
            "onlyalpha.indicator.vwap",
            "onlyalpha.indicator.obv",
            "onlyalpha.indicator.stochastic",
        }:
            raise ValueError(f"unsupported B1 financial Indicator: {definition.type_id}@{definition.semantic_version}")
        return OnlyFinancialTradingBackend(definition)


@dataclass(slots=True)
class OnlyFinancialTradingBackend:
    definition: OnlyCalculationDefinition
    _inputs: dict[str, deque[Decimal | None]] = field(init=False)
    _obv: Decimal = field(init=False, default=Decimal(0))
    _last_close: Decimal | None = field(init=False, default=None)
    _obv_valid: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        limit = self._history_limit()
        self._inputs = {item.name: deque(maxlen=limit) for item in self.definition.inputs}

    @property
    def checkpoint_schema_version(self) -> int:
        return 1

    def capture_checkpoint(self) -> object:
        payload: dict[str, object] = {
            "inputs": {
                name: [None if value is None else str(value) for value in values]
                for name, values in sorted(self._inputs.items())
            },
        }
        if self.definition.type_id.endswith(".obv"):
            payload.update(
                {
                    "last_close": None if self._last_close is None else str(self._last_close),
                    "obv": str(self._obv),
                    "obv_valid": self._obv_valid,
                }
            )
        return payload

    def restore_checkpoint(self, payload: object) -> None:
        expected = (
            {"inputs", "last_close", "obv", "obv_valid"} if self.definition.type_id.endswith(".obv") else {"inputs"}
        )
        if not isinstance(payload, Mapping) or set(payload) != expected or not isinstance(payload["inputs"], Mapping):
            raise ValueError("financial Indicator checkpoint must contain only inputs")
        if set(payload["inputs"]) != set(self._inputs):
            raise ValueError("financial Indicator checkpoint inputs differ")
        restored: dict[str, deque[Decimal | None]] = {}
        lengths: set[int] = set()
        for name, values in payload["inputs"].items():
            if not isinstance(name, str) or not isinstance(values, list):
                raise ValueError("financial checkpoint column invalid")
            if len(values) > self._history_limit():
                raise ValueError("financial checkpoint history exceeds its semantic window")
            restored[name] = deque((_checkpoint_value(value) for value in values), maxlen=self._history_limit())
            lengths.add(len(values))
        if len(lengths) > 1:
            raise ValueError("financial checkpoint input lengths differ")
        self._inputs = restored
        if self.definition.type_id.endswith(".obv"):
            if not isinstance(payload["obv_valid"], bool):
                raise ValueError("financial OBV checkpoint validity must be Boolean")
            self._last_close = _checkpoint_value(payload["last_close"])
            close_history = self._inputs["close"]
            if close_history and close_history[-1] != self._last_close:
                raise ValueError("financial OBV checkpoint last close differs from history")
            self._obv = _required_checkpoint_decimal(payload["obv"])
            self._obv_valid = payload["obv_valid"]

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        if set(inputs) != set(self._inputs):
            raise ValueError("financial Indicator TRADING input names are invalid")
        values = {name: _input_value(value) for name, value in inputs.items()}
        if self.definition.type_id == "onlyalpha.indicator.obv":
            close, volume = values["close"], values["volume"]
            if close is None or volume is None or (self._last_close is None and len(self._inputs["close"]) > 0):
                self._obv_valid = False
            if self._obv_valid and self._last_close is not None and close is not None and volume is not None:
                if close > self._last_close:
                    self._obv += volume
                elif close < self._last_close:
                    self._obv -= volume
            self._last_close = close
            for name, value in values.items():
                self._inputs[name].append(value)
            return {"obv": None if not self._obv_valid else self._quantize(self._obv)}
        for name, value in values.items():
            self._inputs[name].append(value)
        outputs = evaluate_financial(self.definition, self._inputs)
        return {name: values[-1] for name, values in outputs.items()}

    def _history_limit(self) -> int:
        if self.definition.type_id.endswith(".roc"):
            return int(str(self.definition.parameters["period"])) + 1
        if self.definition.type_id.endswith(".stochastic"):
            return (
                int(str(self.definition.parameters["k_period"])) + int(str(self.definition.parameters["d_period"])) - 1
            )
        return int(str(self.definition.parameters.get("period", 1)))

    def _quantize(self, value: Decimal) -> Decimal:
        quantum = self.definition.numeric.output_quantum
        if quantum is None:
            raise ValueError("financial Indicator requires output_quantum")
        return value.quantize(quantum)


def _input_value(value: object) -> Decimal | None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise TypeError("financial Indicator input must be finite Decimal or null")
    return value


def _checkpoint_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("financial checkpoint value must be a Decimal string or null")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("financial checkpoint value must be finite")
    return result


def _required_checkpoint_decimal(value: object) -> Decimal:
    result = _checkpoint_value(value)
    if result is None:
        raise ValueError("financial checkpoint Decimal cannot be null")
    return result


__all__ = [name for name in globals() if name.startswith("Only")]
