"""Market-neutral authority ports carried by a resolved Market Product binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, Self

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.models import (
    OnlyCompiledDynamicPriceRequirement,
    OnlyCompiledNotionalPolicy,
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyMarginModel,
    OnlyPositionAccountingModel,
    OnlySettlementModel,
    OnlyShortSellingRule,
    OnlyTradingSessionModel,
)
from onlyalpha.market.product.identity import OnlyMarketProductAuthorityIdentity

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class OnlyInstrumentTradingStatus(StrEnum):
    """Market-neutral result of interpreting a concrete reference lifecycle."""

    TRADABLE = "TRADABLE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True, slots=True)
class OnlyCompiledInstrumentMarketTerms:
    """Minimal instrument economics required by Core after reference compilation."""

    settlement_currency: str
    contract_multiplier: Decimal
    trading_status: OnlyInstrumentTradingStatus

    def __post_init__(self) -> None:
        if not self.settlement_currency.strip():
            raise ValueError("settlement currency cannot be empty")
        if self.contract_multiplier <= 0:
            raise ValueError("contract multiplier must be positive")


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketPolicyIdentity:
    instrument_id: OnlyInstrumentId
    trading_day: OnlyTradingDay
    reference_fingerprint: str
    compiler: OnlyMarketProductAuthorityIdentity
    policy_fingerprint: str

    def __post_init__(self) -> None:
        for label, value in (
            ("reference fingerprint", self.reference_fingerprint),
            ("policy fingerprint", self.policy_fingerprint),
        ):
            if not _DIGEST.fullmatch(value):
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")

    def canonical_identity(self) -> dict[str, object]:
        return {
            "compiler": self.compiler,
            "instrument_id": str(self.instrument_id),
            "policy_fingerprint": self.policy_fingerprint,
            "reference_fingerprint": self.reference_fingerprint,
            "trading_day": self.trading_day.value,
        }


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketPolicy:
    """Mode-neutral canonical market policy produced by a product compiler."""

    identity: OnlyCompiledMarketPolicyIdentity
    instrument_terms: OnlyCompiledInstrumentMarketTerms
    session_policy: OnlyTradingSessionModel
    price_policy: OnlyCompiledPriceBandPolicy
    quantity_policy: OnlyCompiledQuantityPolicy
    position_policy: OnlyPositionAccountingModel
    short_policy: OnlyShortSellingRule
    settlement_policy: OnlySettlementModel
    margin_policy: OnlyMarginModel | None
    notional_policy: OnlyCompiledNotionalPolicy | None
    dynamic_price_requirements: tuple[OnlyCompiledDynamicPriceRequirement, ...]

    @classmethod
    def create(
        cls,
        *,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        reference_fingerprint: str,
        compiler: OnlyMarketProductAuthorityIdentity,
        instrument_terms: OnlyCompiledInstrumentMarketTerms,
        session_policy: OnlyTradingSessionModel,
        price_policy: OnlyCompiledPriceBandPolicy,
        quantity_policy: OnlyCompiledQuantityPolicy,
        position_policy: OnlyPositionAccountingModel,
        short_policy: OnlyShortSellingRule,
        settlement_policy: OnlySettlementModel,
        margin_policy: OnlyMarginModel | None,
        notional_policy: OnlyCompiledNotionalPolicy | None = None,
        dynamic_price_requirements: tuple[OnlyCompiledDynamicPriceRequirement, ...] = (),
    ) -> Self:
        policies = (
            instrument_terms,
            session_policy,
            price_policy,
            quantity_policy,
            position_policy,
            short_policy,
            settlement_policy,
            margin_policy,
            notional_policy,
            dynamic_price_requirements,
        )
        identity = OnlyCompiledMarketPolicyIdentity(
            instrument_id,
            trading_day,
            reference_fingerprint,
            compiler,
            only_identity_fingerprint(_policy_identity_payload(*policies)),
        )
        return cls(
            identity,
            instrument_terms,
            session_policy,
            price_policy,
            quantity_policy,
            position_policy,
            short_policy,
            settlement_policy,
            margin_policy,
            notional_policy,
            dynamic_price_requirements,
        )

    def __post_init__(self) -> None:
        expected = only_identity_fingerprint(
            _policy_identity_payload(
                self.instrument_terms,
                self.session_policy,
                self.price_policy,
                self.quantity_policy,
                self.position_policy,
                self.short_policy,
                self.settlement_policy,
                self.margin_policy,
                self.notional_policy,
                self.dynamic_price_requirements,
            )
        )
        if self.identity.policy_fingerprint != expected:
            raise ValueError("COMPILED_MARKET_POLICY_FINGERPRINT_CONFLICT")

    def policy_payload(self) -> tuple[object, ...]:
        return (
            self.instrument_terms,
            self.session_policy,
            self.price_policy,
            self.quantity_policy,
            self.position_policy,
            self.short_policy,
            self.settlement_policy,
            self.margin_policy,
            self.notional_policy,
            self.dynamic_price_requirements,
        )


class OnlyMarketPolicyReference(Protocol):
    """Opaque product-owned reference snapshot with canonical content identity."""

    @property
    def content_fingerprint(self) -> str: ...


class OnlyMarketReferenceAuthority(Protocol):
    @property
    def identity(self) -> OnlyMarketProductAuthorityIdentity: ...

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyMarketPolicyReference: ...


@dataclass(frozen=True, slots=True)
class OnlyMarketPolicyCompilationRequest:
    instrument_id: OnlyInstrumentId
    trading_day: OnlyTradingDay
    reference_authority: OnlyMarketReferenceAuthority
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if self.as_of is not None:
            if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
                raise ValueError("MARKET_POLICY_AS_OF_UTC_REQUIRED")
            object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))


class OnlyMarketPolicyCompiler(Protocol):
    """Pure market-semantics compiler; it cannot mutate Trading authorities."""

    @property
    def identity(self) -> OnlyMarketProductAuthorityIdentity: ...

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy: ...


def _policy_identity_payload(
    instrument_terms: OnlyCompiledInstrumentMarketTerms,
    session_policy: OnlyTradingSessionModel,
    price_policy: OnlyCompiledPriceBandPolicy,
    quantity_policy: OnlyCompiledQuantityPolicy,
    position_policy: OnlyPositionAccountingModel,
    short_policy: OnlyShortSellingRule,
    settlement_policy: OnlySettlementModel,
    margin_policy: OnlyMarginModel | None,
    notional_policy: OnlyCompiledNotionalPolicy | None,
    dynamic_price_requirements: tuple[OnlyCompiledDynamicPriceRequirement, ...],
) -> tuple[object, ...]:
    sessions = tuple(
        (
            item.name,
            item.opens_at.isoformat(),
            item.closes_at.isoformat(),
            item.phase,
            item.trading_day_offset,
            item.allows_orders,
        )
        for item in session_policy.sessions
    )
    margin = (
        None
        if margin_policy is None
        else (margin_policy.model_id, margin_policy.initial_rate, margin_policy.maintenance_rate)
    )
    return (
        (
            instrument_terms.settlement_currency,
            instrument_terms.contract_multiplier,
            instrument_terms.trading_status,
        ),
        (session_policy.model_id, session_policy.timezone, sessions, session_policy.continuous_24x7),
        (
            price_policy.regime_id,
            price_policy.tick_size,
            price_policy.previous_close,
            price_policy.daily_limit_rate,
            price_policy.lower_limit,
            price_policy.upper_limit,
            price_policy.rounding_mode,
        ),
        (
            quantity_policy.minimum_buy_quantity,
            quantity_policy.buy_quantity_increment,
            quantity_policy.minimum_sell_quantity,
            quantity_policy.sell_quantity_increment,
            quantity_policy.odd_lot_liquidation_allowed,
            quantity_policy.maximum_limit_order_quantity,
            quantity_policy.allow_fractional,
            quantity_policy.market_minimum_quantity,
            quantity_policy.market_quantity_increment,
            quantity_policy.market_maximum_quantity,
        ),
        (position_policy.mode, position_policy.allow_flip),
        (short_policy.mode,),
        (
            settlement_policy.model_id,
            (settlement_policy.asset_settlement.timing, settlement_policy.asset_settlement.lag),
            (settlement_policy.cash_settlement.timing, settlement_policy.cash_settlement.lag),
            (settlement_policy.asset_availability.timing, settlement_policy.asset_availability.lag),
            (settlement_policy.cash_availability.timing, settlement_policy.cash_availability.lag),
        ),
        margin,
        (
            None
            if notional_policy is None
            else (
                notional_policy.minimum_notional,
                notional_policy.maximum_notional,
                notional_policy.minimum_applies_to_market,
                notional_policy.maximum_applies_to_market,
                notional_policy.market_reference_window_minutes,
            )
        ),
        tuple(
            (
                item.rule_id,
                item.side_specific,
                item.reference_kind,
                item.reference_window_minutes,
                item.bounds,
                item.evaluation_authority,
            )
            for item in dynamic_price_requirements
        ),
    )


__all__ = [name for name in globals() if name.startswith("Only")]
