"""Market-neutral authority ports carried by a resolved Market Product binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Self

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyLiquidityModel,
    OnlyMarginModel,
    OnlyMatchingModel,
    OnlyPositionAccountingModel,
    OnlySettlementModel,
    OnlyShortSellingRule,
    OnlySlippageModel,
    OnlyTradingSessionModel,
)
from onlyalpha.market.product.identity import OnlyMarketProductAuthorityIdentity

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketPolicy:
    """Mode-neutral canonical market policy produced by a product compiler."""

    identity: OnlyCompiledMarketPolicyIdentity
    session_policy: OnlyTradingSessionModel
    price_policy: OnlyCompiledPriceBandPolicy
    quantity_policy: OnlyCompiledQuantityPolicy
    position_policy: OnlyPositionAccountingModel
    short_policy: OnlyShortSellingRule
    settlement_policy: OnlySettlementModel
    margin_policy: OnlyMarginModel | None
    liquidity_policy: OnlyLiquidityModel
    slippage_policy: OnlySlippageModel
    matching_policy: OnlyMatchingModel

    @classmethod
    def create(
        cls,
        *,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        reference_fingerprint: str,
        compiler: OnlyMarketProductAuthorityIdentity,
        session_policy: OnlyTradingSessionModel,
        price_policy: OnlyCompiledPriceBandPolicy,
        quantity_policy: OnlyCompiledQuantityPolicy,
        position_policy: OnlyPositionAccountingModel,
        short_policy: OnlyShortSellingRule,
        settlement_policy: OnlySettlementModel,
        margin_policy: OnlyMarginModel | None,
        liquidity_policy: OnlyLiquidityModel,
        slippage_policy: OnlySlippageModel,
        matching_policy: OnlyMatchingModel,
    ) -> Self:
        policies = (
            session_policy,
            price_policy,
            quantity_policy,
            position_policy,
            short_policy,
            settlement_policy,
            margin_policy,
            liquidity_policy,
            slippage_policy,
            matching_policy,
        )
        identity = OnlyCompiledMarketPolicyIdentity(
            instrument_id,
            trading_day,
            reference_fingerprint,
            compiler,
            only_canonical_fingerprint(policies),
        )
        return cls(
            identity,
            session_policy,
            price_policy,
            quantity_policy,
            position_policy,
            short_policy,
            settlement_policy,
            margin_policy,
            liquidity_policy,
            slippage_policy,
            matching_policy,
        )

    def __post_init__(self) -> None:
        expected = only_canonical_fingerprint(self.policy_payload())
        if self.identity.policy_fingerprint != expected:
            raise ValueError("COMPILED_MARKET_POLICY_FINGERPRINT_CONFLICT")

    def policy_payload(self) -> tuple[object, ...]:
        return (
            self.session_policy,
            self.price_policy,
            self.quantity_policy,
            self.position_policy,
            self.short_policy,
            self.settlement_policy,
            self.margin_policy,
            self.liquidity_policy,
            self.slippage_policy,
            self.matching_policy,
        )


class OnlyMarketPolicyReference(Protocol):
    """Opaque product-owned reference snapshot with canonical content identity."""

    @property
    def content_fingerprint(self) -> str: ...


class OnlyMarketReferenceAuthority(Protocol):
    @property
    def identity(self) -> OnlyMarketProductAuthorityIdentity: ...

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyMarketPolicyReference: ...


@dataclass(frozen=True, slots=True)
class OnlyMarketPolicyCompilationRequest:
    instrument_id: OnlyInstrumentId
    trading_day: OnlyTradingDay
    reference_authority: OnlyMarketReferenceAuthority


class OnlyMarketPolicyCompiler(Protocol):
    """Pure market-semantics compiler; it cannot mutate Trading authorities."""

    @property
    def identity(self) -> OnlyMarketProductAuthorityIdentity: ...

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy: ...


__all__ = [name for name in globals() if name.startswith("Only")]
