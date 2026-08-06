"""Deterministic fee rounding and bounds pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext

from onlyalpha.domain.value import only_decimal
from onlyalpha.fee.models import OnlyFeeCalculationPipeline, OnlyFeeRoundingMode

_ROUNDING = {
    OnlyFeeRoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    OnlyFeeRoundingMode.HALF_UP: ROUND_HALF_UP,
    OnlyFeeRoundingMode.CEILING: ROUND_CEILING,
    OnlyFeeRoundingMode.FLOOR: ROUND_FLOOR,
}


@dataclass(frozen=True, slots=True)
class OnlyFeeRoundingPolicy:
    quantum: Decimal
    mode: OnlyFeeRoundingMode

    def __post_init__(self) -> None:
        quantum = only_decimal(self.quantum)
        if quantum <= 0:
            raise ValueError("fee rounding quantum must be positive")
        object.__setattr__(self, "quantum", quantum)

    def apply(self, amount: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            units = (amount / self.quantum).to_integral_value(rounding=_ROUNDING[self.mode])
            return units * self.quantum


def only_apply_fee_pipeline(
    raw: Decimal,
    *,
    minimum: Decimal | None,
    maximum: Decimal | None,
    rounding: OnlyFeeRoundingPolicy,
    pipeline: OnlyFeeCalculationPipeline,
) -> tuple[Decimal, Decimal]:
    if pipeline is OnlyFeeCalculationPipeline.BOUNDS_THEN_ROUND:
        bounded = _bounds(raw, minimum, maximum)
        return bounded, rounding.apply(bounded)
    rounded = rounding.apply(raw)
    return _bounds(rounded, minimum, maximum), _bounds(rounded, minimum, maximum)


def _bounds(amount: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> Decimal:
    result = amount if minimum is None else max(amount, minimum)
    return result if maximum is None else min(result, maximum)


__all__ = ["OnlyFeeRoundingPolicy", "only_apply_fee_pipeline"]
