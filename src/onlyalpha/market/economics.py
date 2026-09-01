"""Universal compiled market economics consumed by the Trading Kernel."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyReferencePriceKind,
)


class OnlyEconomicModel(StrEnum):
    CASH_EXCHANGE = "CASH_EXCHANGE"
    MARGINED_DERIVATIVE = "MARGINED_DERIVATIVE"


class OnlyMarginIsolationScope(StrEnum):
    ACCOUNT = "ACCOUNT"
    INSTRUMENT = "INSTRUMENT"
    POSITION_LEG = "POSITION_LEG"


@dataclass(frozen=True, slots=True)
class OnlyCompiledOrderCapabilityPolicy:
    supported_order_types: tuple[OnlyOrderType, ...]
    supported_time_in_force: tuple[OnlyTimeInForce, ...]
    supported_position_effects: tuple[OnlyPositionEffect, ...]
    supported_close_scopes: tuple[OnlyCloseScope, ...]
    supported_exposure_constraints: tuple[OnlyExposureConstraint, ...]
    supported_position_modes: tuple[OnlyPositionMode, ...]

    def __post_init__(self) -> None:
        values = (
            self.supported_order_types,
            self.supported_time_in_force,
            self.supported_position_effects,
            self.supported_close_scopes,
            self.supported_exposure_constraints,
            self.supported_position_modes,
        )
        if any(not value for value in values):
            raise ValueError("ORDER_CAPABILITY_SET_EMPTY")
        if any(len(set(value)) != len(value) for value in values):
            raise ValueError("ORDER_CAPABILITY_DUPLICATE")
        if any(
            effect not in {OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE}
            for effect in self.supported_position_effects
        ):
            raise ValueError("ORDER_CAPABILITY_EFFECT_NOT_NORMALIZED")

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.supported_order_types,
            self.supported_time_in_force,
            self.supported_position_effects,
            self.supported_close_scopes,
            self.supported_exposure_constraints,
            self.supported_position_modes,
        )


@dataclass(frozen=True, slots=True)
class OnlyMarginRequirementTier:
    maximum_notional: Decimal | None
    initial_rate: Decimal
    maintenance_rate: Decimal

    def __post_init__(self) -> None:
        if self.maximum_notional is not None and self.maximum_notional <= 0:
            raise ValueError("MARGIN_TIER_MAX_NOTIONAL_INVALID")
        if not Decimal(0) <= self.maintenance_rate <= self.initial_rate <= Decimal(1):
            raise ValueError("MARGIN_TIER_RATES_INVALID")

    def canonical_identity(self) -> tuple[object, ...]:
        return self.maximum_notional, self.initial_rate, self.maintenance_rate


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarginPolicy:
    margin_mode: OnlyMarginMode
    collateral_currency: str
    isolation_scope: OnlyMarginIsolationScope
    valuation_price_kind: OnlyReferencePriceKind
    tiers: tuple[OnlyMarginRequirementTier, ...]

    def __post_init__(self) -> None:
        if self.margin_mode not in {OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED}:
            raise ValueError("COMPILED_MARGIN_MODE_UNSUPPORTED")
        if not self.collateral_currency.strip() or not self.tiers:
            raise ValueError("COMPILED_MARGIN_POLICY_INCOMPLETE")
        if self.margin_mode is OnlyMarginMode.CROSS and self.isolation_scope is not OnlyMarginIsolationScope.ACCOUNT:
            raise ValueError("CROSS_MARGIN_SCOPE_INVALID")
        if self.margin_mode is OnlyMarginMode.ISOLATED and self.isolation_scope is OnlyMarginIsolationScope.ACCOUNT:
            raise ValueError("ISOLATED_MARGIN_SCOPE_INVALID")
        finite = tuple(item.maximum_notional for item in self.tiers if item.maximum_notional is not None)
        if finite != tuple(sorted(finite)) or len(set(finite)) != len(finite):
            raise ValueError("MARGIN_TIERS_NOT_STRICTLY_ORDERED")
        if self.tiers[-1].maximum_notional is not None:
            raise ValueError("MARGIN_TIERS_REQUIRE_OPEN_ENDED_FINAL_TIER")
        if any(item.maximum_notional is None for item in self.tiers[:-1]):
            raise ValueError("MARGIN_OPEN_ENDED_TIER_MUST_BE_LAST")

    def requirement(self, notional: Decimal) -> tuple[Decimal, Decimal]:
        if notional < 0:
            raise ValueError("MARGIN_NOTIONAL_NEGATIVE")
        tier = next(item for item in self.tiers if item.maximum_notional is None or notional <= item.maximum_notional)
        return notional * tier.initial_rate, notional * tier.maintenance_rate

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.margin_mode,
            self.collateral_currency,
            self.isolation_scope,
            self.valuation_price_kind,
            tuple(item.canonical_identity() for item in self.tiers),
        )


@dataclass(frozen=True, slots=True)
class OnlyCompiledValuationPolicy:
    unrealized_price_kind: OnlyReferencePriceKind
    margin_price_kind: OnlyReferencePriceKind

    def canonical_identity(self) -> tuple[object, ...]:
        return self.unrealized_price_kind, self.margin_price_kind


@dataclass(frozen=True, slots=True)
class OnlyCompiledFundingPolicy:
    interval_seconds: int
    valuation_price_kind: OnlyReferencePriceKind
    long_pays_positive_rate: bool = True
    boundary_offset_seconds: int = 0

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("FUNDING_INTERVAL_INVALID")
        if not 0 <= self.boundary_offset_seconds < self.interval_seconds:
            raise ValueError("FUNDING_BOUNDARY_OFFSET_INVALID")

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.interval_seconds,
            self.valuation_price_kind,
            self.long_pays_positive_rate,
            self.boundary_offset_seconds,
        )


@dataclass(frozen=True, slots=True)
class OnlyCompiledVariationMarginPolicy:
    settlement_price_kind: OnlyReferencePriceKind
    reset_cost_basis: bool = True

    def __post_init__(self) -> None:
        if self.settlement_price_kind is not OnlyReferencePriceKind.SETTLEMENT:
            raise ValueError("VARIATION_MARGIN_REQUIRES_SETTLEMENT_PRICE")

    def canonical_identity(self) -> tuple[object, ...]:
        return self.settlement_price_kind, self.reset_cost_basis


__all__ = [name for name in globals() if name.startswith("Only")]
