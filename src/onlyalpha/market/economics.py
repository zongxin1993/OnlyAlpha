"""Universal compiled market economics consumed by the Trading Kernel."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.enums import OnlyCurrencyType, OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyReferencePriceKind,
)
from onlyalpha.identity import only_identity_fingerprint


class OnlyEconomicModel(StrEnum):
    CASH_EXCHANGE = "CASH_EXCHANGE"
    MARGINED_DERIVATIVE = "MARGINED_DERIVATIVE"


class OnlyMarginIsolationScope(StrEnum):
    ACCOUNT = "ACCOUNT"
    INSTRUMENT = "INSTRUMENT"
    POSITION_LEG = "POSITION_LEG"


@dataclass(frozen=True, slots=True)
class OnlyProviderCapabilityEnvelope:
    """Market/provider possibilities; never the effective mode of one run."""

    supported_position_modes: tuple[OnlyPositionMode, ...]
    supported_margin_modes: tuple[OnlyMarginMode, ...]

    def __post_init__(self) -> None:
        if not self.supported_position_modes or not self.supported_margin_modes:
            raise ValueError("TRADING_CAPABILITY_ENVELOPE_EMPTY")
        if len(set(self.supported_position_modes)) != len(self.supported_position_modes) or len(
            set(self.supported_margin_modes)
        ) != len(self.supported_margin_modes):
            raise ValueError("TRADING_CAPABILITY_ENVELOPE_DUPLICATE")
        if any(mode not in {OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED} for mode in self.supported_margin_modes):
            raise ValueError("TRADING_CAPABILITY_MARGIN_MODE_UNSUPPORTED")

    def canonical_identity(self) -> tuple[object, ...]:
        return self.supported_position_modes, self.supported_margin_modes


@dataclass(frozen=True, slots=True)
class OnlyRequestedTradingProfile:
    position_mode: OnlyPositionMode
    margin_mode: OnlyMarginMode
    leverage: Decimal

    def __post_init__(self) -> None:
        if self.margin_mode not in {OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED} or self.leverage < 1:
            raise ValueError("REQUESTED_TRADING_PROFILE_INVALID")

    def canonical_identity(self) -> tuple[object, ...]:
        return self.position_mode, self.margin_mode, self.leverage


@dataclass(frozen=True, slots=True)
class OnlyAccountEffectiveTradingInputs:
    """Account-observed modes used to prove, rather than assume, run semantics."""

    position_mode: OnlyPositionMode
    margin_mode: OnlyMarginMode
    leverage: Decimal
    source_fingerprint: str

    def __post_init__(self) -> None:
        if self.margin_mode not in {OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED} or self.leverage < 1:
            raise ValueError("ACCOUNT_EFFECTIVE_TRADING_INPUTS_INVALID")
        if len(self.source_fingerprint) != 64 or any(
            value not in "0123456789abcdef" for value in self.source_fingerprint
        ):
            raise ValueError("ACCOUNT_EFFECTIVE_SOURCE_FINGERPRINT_INVALID")

    def canonical_identity(self) -> tuple[object, ...]:
        return self.position_mode, self.margin_mode, self.leverage, self.source_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyEffectiveTradingProfile:
    """The single effective position/margin-mode authority for one run."""

    position_mode: OnlyPositionMode
    margin_mode: OnlyMarginMode
    leverage: Decimal
    account_effective_source_fingerprint: str
    profile_fingerprint: str

    @classmethod
    def resolve(
        cls,
        capability: OnlyProviderCapabilityEnvelope,
        requested: OnlyRequestedTradingProfile,
        account_effective: OnlyAccountEffectiveTradingInputs,
    ) -> OnlyEffectiveTradingProfile:
        if requested.position_mode not in capability.supported_position_modes:
            raise ValueError("REQUESTED_POSITION_MODE_UNSUPPORTED")
        if requested.margin_mode not in capability.supported_margin_modes:
            raise ValueError("REQUESTED_MARGIN_MODE_UNSUPPORTED")
        requested_values = (requested.position_mode, requested.margin_mode, requested.leverage)
        effective_values = (
            account_effective.position_mode,
            account_effective.margin_mode,
            account_effective.leverage,
        )
        if requested_values != effective_values:
            raise ValueError("ACCOUNT_EFFECTIVE_TRADING_PROFILE_MISMATCH")
        payload = (*effective_values, account_effective.source_fingerprint)
        return cls(*effective_values, account_effective.source_fingerprint, only_identity_fingerprint(payload))

    def __post_init__(self) -> None:
        payload = (
            self.position_mode,
            self.margin_mode,
            self.leverage,
            self.account_effective_source_fingerprint,
        )
        if self.leverage < 1 or self.profile_fingerprint != only_identity_fingerprint(payload):
            raise ValueError("EFFECTIVE_TRADING_PROFILE_FINGERPRINT_CONFLICT")

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.position_mode,
            self.margin_mode,
            self.leverage,
            self.account_effective_source_fingerprint,
        )


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
class OnlyMarginRequirementSegment:
    lower_bound: Decimal
    upper_bound: Decimal | None
    initial_slope: Decimal
    initial_intercept: Decimal
    maintenance_slope: Decimal
    maintenance_intercept: Decimal

    def __post_init__(self) -> None:
        if self.lower_bound < 0 or (self.upper_bound is not None and self.upper_bound <= self.lower_bound):
            raise ValueError("MARGIN_SEGMENT_BOUNDS_INVALID")
        if self.initial_slope < 0 or self.maintenance_slope < 0:
            raise ValueError("MARGIN_SEGMENT_SLOPE_INVALID")
        for notional in (self.lower_bound, self.upper_bound):
            if notional is None:
                continue
            initial, maintenance = self.requirement(notional)
            if initial < 0 or maintenance < 0 or maintenance > initial:
                raise ValueError("MARGIN_SEGMENT_REQUIREMENT_INVALID")

    def requirement(self, notional: Decimal) -> tuple[Decimal, Decimal]:
        return (
            self.initial_slope * notional + self.initial_intercept,
            self.maintenance_slope * notional + self.maintenance_intercept,
        )

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.lower_bound,
            self.upper_bound,
            self.initial_slope,
            self.initial_intercept,
            self.maintenance_slope,
            self.maintenance_intercept,
        )


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarginPolicy:
    collateral_currency: str
    isolation_scope: OnlyMarginIsolationScope
    valuation_price_kind: OnlyReferencePriceKind
    segments: tuple[OnlyMarginRequirementSegment, ...]
    collateral_currency_precision: int = 2
    collateral_currency_type: OnlyCurrencyType = OnlyCurrencyType.FIAT

    def __post_init__(self) -> None:
        if (
            not self.collateral_currency.strip()
            or not 0 <= self.collateral_currency_precision <= 18
            or not self.segments
        ):
            raise ValueError("COMPILED_MARGIN_POLICY_INCOMPLETE")
        if self.segments[0].lower_bound != 0:
            raise ValueError("MARGIN_SEGMENTS_DOMAIN_INCOMPLETE")
        for current, following in zip(self.segments, self.segments[1:], strict=False):
            if current.upper_bound != following.lower_bound:
                raise ValueError("MARGIN_SEGMENTS_NOT_CONTIGUOUS")
            boundary = current.upper_bound
            if boundary is None:
                raise ValueError("MARGIN_OPEN_ENDED_SEGMENT_MUST_BE_LAST")
            current_initial, current_maintenance = current.requirement(boundary)
            next_initial, next_maintenance = following.requirement(boundary)
            if current_initial != next_initial or current_maintenance != next_maintenance:
                raise ValueError("MARGIN_SEGMENTS_DISCONTINUOUS")

    def requirement(self, notional: Decimal) -> tuple[Decimal, Decimal]:
        if notional < 0:
            raise ValueError("MARGIN_NOTIONAL_NEGATIVE")
        segment = next(
            (
                item
                for index, item in enumerate(self.segments)
                if item.lower_bound <= notional
                and (
                    item.upper_bound is None
                    or notional < item.upper_bound
                    or (index == len(self.segments) - 1 and notional == item.upper_bound)
                )
            ),
            None,
        )
        if segment is None:
            raise ValueError("MARGIN_NOTIONAL_OUTSIDE_COMPILED_DOMAIN")
        initial, maintenance = segment.requirement(notional)
        if initial < 0 or maintenance < 0 or maintenance > initial:
            raise ValueError("MARGIN_REQUIREMENT_INVALID")
        return initial, maintenance

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.collateral_currency,
            self.isolation_scope,
            self.valuation_price_kind,
            tuple(item.canonical_identity() for item in self.segments),
            self.collateral_currency_precision,
            self.collateral_currency_type,
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
