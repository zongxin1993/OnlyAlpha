"""Exact incremental TRADING Operator backend."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from onlyalpha.calculation import OnlyCalculationDefinition
from onlyalpha_plugin_operators.semantics import evaluate

_SUPPORTED = {
    "onlyalpha.operator.add",
    "onlyalpha.operator.subtract",
    "onlyalpha.operator.multiply",
    "onlyalpha.operator.divide",
    "onlyalpha.operator.abs",
    "onlyalpha.operator.sign",
    "onlyalpha.operator.log",
    "onlyalpha.operator.delay",
    "onlyalpha.operator.delta",
    "onlyalpha.operator.rolling_mean",
    "onlyalpha.operator.rolling_sum",
    "onlyalpha.operator.rolling_std",
    "onlyalpha.operator.rolling_var",
    "onlyalpha.operator.rolling_min",
    "onlyalpha.operator.rolling_max",
    "onlyalpha.operator.rolling_covariance",
    "onlyalpha.operator.rolling_correlation",
    "onlyalpha.operator.ts_rank",
    "onlyalpha.operator.scale",
    "onlyalpha.operator.decay_linear",
}


class OnlyOfficialTradingOperatorBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        if definition.semantic_version != "1" or definition.type_id not in _SUPPORTED:
            raise ValueError(
                f"unsupported official TRADING Operator: {definition.type_id}@{definition.semantic_version}"
            )
        if "period" not in definition.parameters:
            return OnlyOfficialTradingStatelessOperatorBackend(definition)
        return OnlyOfficialTradingStatefulOperatorBackend(definition)


@dataclass(frozen=True, slots=True)
class OnlyOfficialTradingStatelessOperatorBackend:
    definition: OnlyCalculationDefinition

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        columns = {name: (_value(value),) for name, value in inputs.items()}
        return {name: values[-1] for name, values in evaluate(self.definition, columns).items()}


@dataclass(slots=True)
class OnlyOfficialTradingStatefulOperatorBackend:
    definition: OnlyCalculationDefinition
    _windows: dict[str, deque[Decimal | None]] = field(init=False)

    def __post_init__(self) -> None:
        period = int(str(self.definition.parameters["period"]))
        size = period + 1 if self.definition.type_id.endswith((".delay", ".delta")) else period
        self._windows = {item.name: deque(maxlen=size) for item in self.definition.inputs}

    @property
    def checkpoint_schema_version(self) -> int:
        return 2 if self.definition.type_id == "onlyalpha.operator.rolling_mean" else 1

    def capture_checkpoint(self) -> object:
        return {
            "inputs": {
                name: [None if value is None else str(value) for value in values]
                for name, values in sorted(self._windows.items())
            }
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping) or set(payload) != {"inputs"} or not isinstance(payload["inputs"], Mapping):
            raise ValueError("Operator checkpoint must contain only an inputs object")
        if set(payload["inputs"]) != set(self._windows):
            raise ValueError("Operator checkpoint input names differ")
        limit = next(iter(self._windows.values())).maxlen
        restored: dict[str, deque[Decimal | None]] = {}
        for name, raw in payload["inputs"].items():
            if not isinstance(name, str) or not isinstance(raw, list) or len(raw) > int(limit or 0):
                raise ValueError("Operator checkpoint input history is invalid")
            restored[name] = deque((_checkpoint_value(value) for value in raw), maxlen=limit)
        self._windows = restored

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        if set(inputs) != set(self._windows):
            raise ValueError("Operator TRADING input names are invalid")
        for name, value in inputs.items():
            self._windows[name].append(_value(value))
        outputs = evaluate(self.definition, self._windows)
        return {name: values[-1] for name, values in outputs.items()}


def _value(value: object) -> Decimal | None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise TypeError("Operator TRADING input must be finite Decimal or null")
    return value


def _checkpoint_value(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Operator checkpoint values must be Decimal strings or null")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Operator checkpoint values must be finite")
    return result


__all__ = [name for name in globals() if name.startswith("Only")]
