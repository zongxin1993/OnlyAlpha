"""Pure compilation of normalized USD-M authorities into canonical economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from onlyalpha.domain.enums import OnlyCurrencyType, OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.trading import OnlyCloseScope, OnlyExposureConstraint, OnlyPositionEffect, OnlyReferencePriceKind
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import (
    OnlyCompiledFundingPolicy,
    OnlyCompiledMarginPolicy,
    OnlyCompiledOrderCapabilityPolicy,
    OnlyCompiledValuationPolicy,
    OnlyEconomicModel,
    OnlyMarginIsolationScope,
)
from onlyalpha.market.models import (
    OnlyCompiledNotionalPolicy,
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

from .reference import (
    BINANCE_USDM_CAPABILITY,
    OnlyBinanceUsdmAccountReferenceAuthority,
    OnlyBinanceUsdmPublicMarketReference,
)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmPolicyCompiler:
    account_reference_authority: OnlyBinanceUsdmAccountReferenceAuthority

    @property
    def identity(self) -> OnlyMarketProductAuthorityIdentity:
        return OnlyMarketProductAuthorityIdentity(
            "POLICY_COMPILER",
            "BINANCE_USDM",
            "2",
            only_identity_fingerprint(
                (
                    "LINEAR_PERPETUAL_CANONICAL_POLICY@2",
                    self.account_reference_authority.identity,
                    BINANCE_USDM_CAPABILITY,
                )
            ),
        )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        public = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        if not isinstance(public, OnlyBinanceUsdmPublicMarketReference):
            raise TypeError("BINANCE_USDM_PUBLIC_REFERENCE_REQUIRED")
        account = self.account_reference_authority.resolve(
            request.instrument_id, request.trading_day, as_of=request.as_of
        )
        profile = request.effective_trading_profile
        if (
            profile is None
            or profile.account_effective_source_fingerprint != account.effective_inputs.source_fingerprint
        ):
            raise ValueError("BINANCE_USDM_EFFECTIVE_TRADING_PROFILE_REQUIRED")
        immediate = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
        status = (
            OnlyInstrumentTradingStatus.TRADABLE
            if public.provider_status == "TRADING"
            else OnlyInstrumentTradingStatus.SUSPENDED
            if public.provider_status in {"PRE_TRADING", "PENDING_TRADING"}
            else OnlyInstrumentTradingStatus.INACTIVE
        )
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=only_identity_fingerprint((public.content_fingerprint, account.content_fingerprint)),
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(
                public.settlement_currency, public.contract_multiplier, status
            ),
            session_policy=OnlyTradingSessionModel(
                "CRYPTO_DERIVATIVE_24X7",
                "UTC",
                (OnlyTradingSessionDefinition("continuous", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
                True,
            ),
            price_policy=OnlyCompiledPriceBandPolicy(
                "BINANCE_USDM_STATIC@2",
                public.price_tick,
                None,
                None,
                public.minimum_price,
                public.maximum_price,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                public.minimum_quantity,
                public.quantity_step,
                public.minimum_quantity,
                public.quantity_step,
                False,
                public.maximum_quantity,
                True,
            ),
            position_policy=OnlyPositionAccountingModel(),
            short_policy=OnlyShortSellingRule(OnlyShortSellingMode.ENABLED_UNRESTRICTED),
            settlement_policy=OnlySettlementModel(
                "BINANCE_USDM_CONTINUOUS", immediate, immediate, immediate, immediate
            ),
            margin_policy=None,
            notional_policy=OnlyCompiledNotionalPolicy(public.minimum_notional, None, True, False, 0),
            economic_model=OnlyEconomicModel.MARGINED_DERIVATIVE,
            order_capability_policy=OnlyCompiledOrderCapabilityPolicy(
                (OnlyOrderType.MARKET, OnlyOrderType.LIMIT),
                (OnlyTimeInForce.GTC, OnlyTimeInForce.IOC, OnlyTimeInForce.FOK),
                (OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE),
                (OnlyCloseScope.ANY,),
                (OnlyExposureConstraint.NONE, OnlyExposureConstraint.REDUCE_ONLY),
                BINANCE_USDM_CAPABILITY[0],
            ),
            compiled_margin_policy=OnlyCompiledMarginPolicy(
                public.settlement_currency,
                OnlyMarginIsolationScope.ACCOUNT
                if profile.margin_mode is OnlyMarginMode.CROSS
                else OnlyMarginIsolationScope.POSITION_LEG,
                OnlyReferencePriceKind.MARK,
                account.margin_segments,
                8,
                OnlyCurrencyType.CRYPTO,
            ),
            valuation_policy=OnlyCompiledValuationPolicy(OnlyReferencePriceKind.MARK, OnlyReferencePriceKind.MARK),
            funding_policy=OnlyCompiledFundingPolicy(
                public.funding_schedule.interval_seconds,
                public.funding_schedule.valuation_price_kind,
                True,
                public.funding_schedule.boundary_offset_seconds,
            ),
            effective_trading_profile=profile,
        )


__all__ = ["OnlyBinanceUsdmPolicyCompiler"]
