"""Canonical Decimal execution environment for Calculation implementations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Clamped,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from types import MappingProxyType
from typing import ClassVar

from onlyalpha.calculation.definition import OnlyNumericDefinition
from onlyalpha.calculation.implementation import OnlyCalculationSemanticDependency
from onlyalpha.canonical import only_canonical_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyDecimalExecutionPolicy:
    policy_id: str
    semantic_version: str
    emin: int
    emax: int
    capitals: int
    clamp: int
    trapped_signals: tuple[str, ...]

    _DOMAIN: ClassVar[str] = "onlyalpha.decimal.execution-policy"

    def __post_init__(self) -> None:
        if self.policy_id != "onlyalpha.decimal.execution":
            raise ValueError("Decimal execution policy id is invalid")
        if not self.semantic_version or any(char.isspace() for char in self.semantic_version):
            raise ValueError("Decimal execution policy semantic version is invalid")
        if self.emin >= self.emax or self.capitals not in {0, 1} or self.clamp not in {0, 1}:
            raise ValueError("Decimal execution policy envelope is invalid")
        if self.trapped_signals != tuple(sorted(set(self.trapped_signals))):
            raise ValueError("Decimal execution trapped signals must be unique and sorted")

    @property
    def canonical_payload(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "domain": self._DOMAIN,
                "policy_id": self.policy_id,
                "semantic_version": self.semantic_version,
                "emin": self.emin,
                "emax": self.emax,
                "capitals": self.capitals,
                "clamp": self.clamp,
                "trapped_signals": list(self.trapped_signals),
                "entry_flags": "CLEAR",
            }
        )

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.canonical_payload)


ONLY_DECIMAL_EXECUTION_POLICY_V1 = OnlyDecimalExecutionPolicy(
    policy_id="onlyalpha.decimal.execution",
    semantic_version="1",
    emin=-999999,
    emax=999999,
    capitals=1,
    clamp=0,
    trapped_signals=("DivisionByZero", "InvalidOperation", "Overflow"),
)

_SIGNALS = (
    InvalidOperation,
    FloatOperation,
    DivisionByZero,
    Overflow,
    Underflow,
    Subnormal,
    Inexact,
    Rounded,
    Clamped,
)
_SIGNALS_BY_NAME = MappingProxyType({signal.__name__: signal for signal in _SIGNALS})
_ROUNDINGS_BY_NAME = MappingProxyType(
    {
        value: value
        for value in (
            ROUND_05UP,
            ROUND_CEILING,
            ROUND_DOWN,
            ROUND_FLOOR,
            ROUND_HALF_DOWN,
            ROUND_HALF_EVEN,
            ROUND_HALF_UP,
            ROUND_UP,
        )
    }
)


def only_decimal_context(numeric: OnlyNumericDefinition) -> Context:
    """Construct a complete context without consulting ambient Decimal state."""

    policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
    trapped = set(policy.trapped_signals)
    if not trapped <= set(_SIGNALS_BY_NAME):
        raise ValueError("Decimal execution policy contains an unknown signal")
    try:
        rounding = _ROUNDINGS_BY_NAME[numeric.rounding]
    except KeyError as exc:
        raise ValueError("Calculation Decimal rounding is unsupported") from exc
    context = Context(
        prec=numeric.precision,
        rounding=rounding,
        Emin=policy.emin,
        Emax=policy.emax,
        capitals=policy.capitals,
        clamp=policy.clamp,
        flags={signal: False for signal in _SIGNALS},
        traps={signal: signal.__name__ in trapped for signal in _SIGNALS},
    )
    context.clear_flags()
    return context


def only_quantize_decimal(numeric: OnlyNumericDefinition, value: Decimal) -> Decimal:
    """Quantize one value under the same complete canonical execution context."""

    if numeric.output_quantum is None:
        raise ValueError("Decimal quantization requires output_quantum")
    with localcontext(only_decimal_context(numeric)):
        return value.quantize(numeric.output_quantum)


def only_decimal_execution_semantic_dependency() -> OnlyCalculationSemanticDependency:
    policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
    return OnlyCalculationSemanticDependency(policy.policy_id, policy.semantic_version, policy.fingerprint)


__all__ = [
    "ONLY_DECIMAL_EXECUTION_POLICY_V1",
    "OnlyDecimalExecutionPolicy",
    "only_decimal_context",
    "only_decimal_execution_semantic_dependency",
    "only_quantize_decimal",
]
