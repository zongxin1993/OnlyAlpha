"""Exact incremental TRADING Operator backend."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from onlyalpha.calculation import OnlyCalculationDefinition


class OnlyOfficialTradingOperatorBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        if definition.type_id != "onlyalpha.operator.rolling_mean" or definition.semantic_version != "1":
            raise ValueError(
                f"unsupported official TRADING Operator: {definition.type_id}@{definition.semantic_version}"
            )
        return OnlyOfficialTradingRollingMeanBackend(definition)


@dataclass(slots=True)
class OnlyOfficialTradingRollingMeanBackend:
    definition: OnlyCalculationDefinition
    _window: deque[Decimal | None] = field(init=False)

    def __post_init__(self) -> None:
        self._window = deque(maxlen=int(str(self.definition.parameters["period"])))

    @property
    def checkpoint_schema_version(self) -> int:
        return 1

    def capture_checkpoint(self) -> object:
        return {"values": [None if item is None else str(item) for item in self._window]}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or set(payload) != {"values"} or not isinstance(payload["values"], list):
            raise ValueError("Rolling Mean checkpoint must contain only a values array")
        period = int(str(self.definition.parameters["period"]))
        if len(payload["values"]) > period:
            raise ValueError("Rolling Mean checkpoint exceeds the declared period")
        self._window = deque(
            (None if item is None else Decimal(str(item)) for item in payload["values"]),
            maxlen=period,
        )

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        if set(inputs) != {"value"}:
            raise ValueError("Rolling Mean TRADING inputs are invalid")
        value = inputs["value"]
        if value is not None and not isinstance(value, Decimal):
            raise TypeError("Rolling Mean TRADING input must be Decimal or null")
        self._window.append(value)
        period = int(str(self.definition.parameters["period"]))
        if len(self._window) < period or any(item is None for item in self._window):
            return {"value": None}
        quantum = self.definition.numeric.output_quantum
        if quantum is None:
            raise ValueError("Rolling Mean requires an output quantum")
        with localcontext() as context:
            context.prec = self.definition.numeric.precision
            context.rounding = self.definition.numeric.rounding
            result = (sum((item for item in self._window if item is not None), Decimal(0)) / period).quantize(quantum)
        return {"value": result}


__all__ = [name for name in globals() if name.startswith("Only")]
