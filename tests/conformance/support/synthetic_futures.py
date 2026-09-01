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
    OnlyAccountEffectiveTradingInputs,
    OnlyCompiledMarginPolicy,
    OnlyCompiledOrderCapabilityPolicy,
    OnlyCompiledValuationPolicy,
    OnlyCompiledVariationMarginPolicy,
    OnlyEconomicModel,
    OnlyEffectiveTradingProfile,
    OnlyMarginIsolationScope,
    OnlyMarginRequirementSegment,
    OnlyProviderCapabilityEnvelope,
    OnlyRequestedTradingProfile,
)
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
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
        profile = request.effective_trading_profile
        if profile is None:
            raise ValueError("SYNTHETIC_FUTURES_EFFECTIVE_TRADING_PROFILE_REQUIRED")
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
            position_policy=OnlyPositionAccountingModel(),
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
                (OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING),
            ),
            compiled_margin_policy=OnlyCompiledMarginPolicy(
                "USD",
                OnlyMarginIsolationScope.ACCOUNT
                if profile.margin_mode is OnlyMarginMode.CROSS
                else OnlyMarginIsolationScope.POSITION_LEG,
                OnlyReferencePriceKind.SETTLEMENT,
                (
                    OnlyMarginRequirementSegment(
                        Decimal(0),
                        None,
                        Decimal("0.12"),
                        Decimal(0),
                        Decimal("0.08"),
                        Decimal(0),
                    ),
                ),
            ),
            valuation_policy=OnlyCompiledValuationPolicy(
                OnlyReferencePriceKind.SETTLEMENT, OnlyReferencePriceKind.SETTLEMENT
            ),
            variation_margin_policy=OnlyCompiledVariationMarginPolicy(OnlyReferencePriceKind.SETTLEMENT),
            effective_trading_profile=profile,
        )


def only_synthetic_futures_effective_profile(
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    margin_mode: OnlyMarginMode = OnlyMarginMode.CROSS,
) -> OnlyEffectiveTradingProfile:
    capability = OnlyProviderCapabilityEnvelope(
        (OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING),
        (OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED),
    )
    requested = OnlyRequestedTradingProfile(position_mode, margin_mode, Decimal("10"))
    account = OnlyAccountEffectiveTradingInputs(
        position_mode,
        margin_mode,
        Decimal("10"),
        only_identity_fingerprint(("SYNTHETIC_ACCOUNT", position_mode, margin_mode, "10")),
    )
    return OnlyEffectiveTradingProfile.resolve(capability, requested, account)


__all__ = [
    "OnlySyntheticFuturesPolicyCompiler",
    "OnlySyntheticFuturesReferenceAuthority",
    "only_synthetic_futures_effective_profile",
]
