"""Pure provider-neutral 24x7 Spot policy compiler."""

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from onlyalpha.plugin.api import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketPositionMode,
    OnlyMarketProductAuthorityIdentity,
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
    only_identity_fingerprint,
)
from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReference

_IMMEDIATE = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
_SESSION = OnlyTradingSessionModel(
    "CRYPTO_SPOT_24X7",
    "UTC",
    (OnlyTradingSessionDefinition("continuous", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
    True,
)
_SETTLEMENT = OnlySettlementModel("CRYPTO_SPOT_IMMEDIATE", _IMMEDIATE, _IMMEDIATE, _IMMEDIATE, _IMMEDIATE)
_POSITION = OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY)
_SHORT = OnlyShortSellingRule(OnlyShortSellingMode.DISABLED)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER",
        "BINANCE_SPOT",
        "1",
        only_identity_fingerprint(
            ("CRYPTO_SPOT_24X7", "UTC", "IMMEDIATE", "LONG_ONLY", "NO_MARGIN", "REFERENCE_STATIC_RULES")
        ),
    )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day)
        if not isinstance(reference, OnlyBinanceSpotReference):
            raise TypeError("BINANCE_SPOT_REFERENCE_TYPE_REQUIRED")
        status = (
            OnlyInstrumentTradingStatus.TRADABLE
            if reference.trade_eligible
            else (
                OnlyInstrumentTradingStatus.SUSPENDED
                if reference.provider_status in {"HALT", "BREAK"}
                else OnlyInstrumentTradingStatus.INACTIVE
            )
        )
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(reference.quote_currency, Decimal("1"), status),
            session_policy=_SESSION,
            price_policy=OnlyCompiledPriceBandPolicy(
                "BINANCE_SPOT_STATIC@1",
                reference.price_tick,
                None,
                None,
                reference.minimum_price,
                reference.maximum_price,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                reference.minimum_quantity,
                reference.quantity_step,
                reference.minimum_quantity,
                reference.quantity_step,
                False,
                reference.maximum_quantity,
                True,
            ),
            position_policy=_POSITION,
            short_policy=_SHORT,
            settlement_policy=_SETTLEMENT,
            margin_policy=None,
        )


__all__ = ["OnlyBinanceSpotPolicyCompiler"]
