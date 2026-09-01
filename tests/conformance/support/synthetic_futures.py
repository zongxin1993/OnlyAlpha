"""Hermetic non-provider Futures Market Product conformance fixture."""

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyReferencePriceKind,
)
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import (
    OnlyCompiledMarginPolicy,
    OnlyCompiledOrderCapabilityPolicy,
    OnlyCompiledValuationPolicy,
    OnlyCompiledVariationMarginPolicy,
    OnlyEconomicModel,
    OnlyMarginIsolationScope,
    OnlyMarginRequirementTier,
)
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyMarketPositionMode,
    OnlyPositionAccountingModel,
    OnlyPriceBandRoundingMode,
    OnlySettlementModel,
    OnlySettlementRule,
    OnlySettlementTiming,
    OnlyShortSellingMode,
    OnlyShortSellingRule,
    OnlyTradingPhase,
    OnlyTradingSessionDefinition,
    OnlyTradingSessionModel,
)
from onlyalpha.market.product import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductAuthorityIdentity,
)


@dataclass(frozen=True, slots=True)
class OnlySyntheticFuturesReference:
    content_fingerprint: str = only_identity_fingerprint(("TEST_LINEAR_FUTURE", "2026-12-31"))


@dataclass(frozen=True, slots=True)
class OnlySyntheticFuturesReferenceAuthority:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "REFERENCE",
        "TEST_LINEAR_FUTURE",
        "1",
        only_identity_fingerprint(("TEST_LINEAR_FUTURE", "2026-12-31")),
    )

    def resolve(self, instrument_id, trading_day, *, as_of=None):
        del instrument_id, trading_day, as_of
        return OnlySyntheticFuturesReference()


@dataclass(frozen=True, slots=True)
class OnlySyntheticFuturesPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER",
        "TEST_LINEAR_FUTURE",
        "1",
        only_identity_fingerprint(("DAILY_MTM", "CROSS", "NO_FUNDING")),
    )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        immediate = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(
                "USD", Decimal("10"), OnlyInstrumentTradingStatus.TRADABLE
            ),
            session_policy=OnlyTradingSessionModel(
                "TEST_SESSION",
                "UTC",
                (OnlyTradingSessionDefinition("day", time(9), time(17), OnlyTradingPhase.CONTINUOUS),),
            ),
            price_policy=OnlyCompiledPriceBandPolicy(
                "TEST", Decimal("0.01"), None, None, None, None, OnlyPriceBandRoundingMode.HALF_UP_TO_TICK
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), False, None, False
            ),
            position_policy=OnlyPositionAccountingModel(OnlyMarketPositionMode.NETTING),
            short_policy=OnlyShortSellingRule(OnlyShortSellingMode.ENABLED_UNRESTRICTED),
            settlement_policy=OnlySettlementModel("DAILY_MTM", immediate, immediate, immediate, immediate),
            margin_policy=None,
            economic_model=OnlyEconomicModel.MARGINED_DERIVATIVE,
            order_capability_policy=OnlyCompiledOrderCapabilityPolicy(
                (OnlyOrderType.LIMIT,),
                (OnlyTimeInForce.GTC,),
                (OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE),
                (OnlyCloseScope.ANY,),
                (OnlyExposureConstraint.NONE, OnlyExposureConstraint.REDUCE_ONLY),
                (OnlyPositionMode.NETTING,),
            ),
            compiled_margin_policy=OnlyCompiledMarginPolicy(
                OnlyMarginMode.CROSS,
                "USD",
                OnlyMarginIsolationScope.ACCOUNT,
                OnlyReferencePriceKind.SETTLEMENT,
                (OnlyMarginRequirementTier(None, Decimal("0.12"), Decimal("0.08")),),
            ),
            valuation_policy=OnlyCompiledValuationPolicy(
                OnlyReferencePriceKind.SETTLEMENT, OnlyReferencePriceKind.SETTLEMENT
            ),
            variation_margin_policy=OnlyCompiledVariationMarginPolicy(OnlyReferencePriceKind.SETTLEMENT),
        )


__all__ = ["OnlySyntheticFuturesPolicyCompiler", "OnlySyntheticFuturesReferenceAuthority"]
