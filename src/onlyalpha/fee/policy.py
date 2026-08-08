"""Versioned fee rule and resolved-policy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.value import OnlyCurrency, only_decimal
from onlyalpha.fee.formula import OnlyFeeFormula
from onlyalpha.fee.models import (
    OnlyFeeAuthority,
    OnlyFeeCalculationPipeline,
    OnlyFeeCalculationScope,
    OnlyFeeEconomicDirection,
    OnlyFeeResolutionPolicy,
    OnlyFeeScheduleAuthority,
    OnlyFeeType,
    only_fee_fingerprint,
)
from onlyalpha.fee.rounding import OnlyFeeRoundingPolicy


@dataclass(frozen=True, slots=True)
class OnlyFeeRule:
    rule_id: str
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    economic_direction: OnlyFeeEconomicDirection
    formula: OnlyFeeFormula
    calculation_scope: OnlyFeeCalculationScope
    resolution_policy: OnlyFeeResolutionPolicy
    minimum: Decimal | None
    maximum: Decimal | None
    side: OnlyOrderSide | None
    offset: OnlyOffset | None
    liquidity_role: OnlyLiquiditySide | None
    rounding: OnlyFeeRoundingPolicy
    pipeline: OnlyFeeCalculationPipeline

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("fee rule ID cannot be empty")
        minimum = None if self.minimum is None else only_decimal(self.minimum)
        maximum = None if self.maximum is None else only_decimal(self.maximum)
        if minimum is not None and minimum < 0 or maximum is not None and maximum < 0:
            raise ValueError("fee rule bounds cannot be negative")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("fee rule minimum cannot exceed maximum")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    @property
    def fingerprint(self) -> str:
        return only_fee_fingerprint(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "fee_type": self.fee_type.value,
            "authority": self.authority.value,
            "economic_direction": self.economic_direction.value,
            "formula": self.formula.payload(),
            "calculation_scope": self.calculation_scope.value,
            "resolution_policy": self.resolution_policy.value,
            "minimum": None if self.minimum is None else str(self.minimum),
            "maximum": None if self.maximum is None else str(self.maximum),
            "side": None if self.side is None else self.side.value,
            "offset": None if self.offset is None else self.offset.value,
            "liquidity_role": None if self.liquidity_role is None else self.liquidity_role.value,
            "rounding": {"quantum": str(self.rounding.quantum), "mode": self.rounding.mode.value},
            "pipeline": self.pipeline.value,
        }

    def matches(self, side: OnlyOrderSide, offset: OnlyOffset, liquidity_role: OnlyLiquiditySide | None) -> bool:
        return (
            (self.side is None or self.side is side)
            and (self.offset is None or self.offset is offset)
            and (self.liquidity_role is None or self.liquidity_role is liquidity_role)
        )


@dataclass(frozen=True, slots=True)
class OnlyResolvedFeePolicy:
    schedule_authority: OnlyFeeScheduleAuthority
    schedule_id: str
    schedule_version: str
    schedule_fingerprint: str
    source_id: str
    currency: OnlyCurrency
    rule: OnlyFeeRule


@dataclass(frozen=True, slots=True)
class OnlyResolvedFeePolicySet:
    policies: tuple[OnlyResolvedFeePolicy, ...]
    fingerprint: str

    @classmethod
    def create(cls, policies: tuple[OnlyResolvedFeePolicy, ...]) -> OnlyResolvedFeePolicySet:
        ordered = tuple(
            sorted(
                policies,
                key=lambda item: (
                    item.schedule_authority.value,
                    item.schedule_id,
                    item.schedule_version,
                    item.rule.rule_id,
                ),
            )
        )
        return cls(
            ordered,
            only_fee_fingerprint(
                tuple(
                    (
                        item.schedule_authority.value,
                        item.schedule_fingerprint,
                        item.rule.fingerprint,
                        item.currency.code,
                    )
                    for item in ordered
                )
            ),
        )


__all__ = ["OnlyFeeRule", "OnlyResolvedFeePolicy", "OnlyResolvedFeePolicySet"]
