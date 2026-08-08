"""Architecture-only generic cash fee pack."""

from datetime import date
from decimal import Decimal

from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.formula import OnlyFeeFormula, OnlyFeeRateTerm
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.fee.models import (
    OnlyFeeAuthority,
    OnlyFeeCalculationBasis,
    OnlyFeeCalculationPipeline,
    OnlyFeeCalculationScope,
    OnlyFeeEconomicDirection,
    OnlyFeeResolutionPolicy,
    OnlyFeeRoundingMode,
    OnlyFeeType,
)
from onlyalpha.fee.policy import OnlyFeeRule
from onlyalpha.fee.rounding import OnlyFeeRoundingPolicy
from onlyalpha.fee.schedules import OnlyMarketFeeSchedule


def _cash_pack(*, pack_id: str, profile_id: str, market: str) -> OnlyMarketFeePack:
    schedule = OnlyMarketFeeSchedule(
        "GENERIC_T0_CASH_FEES",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("CNY"),
        "OnlyAlpha Generic Conformance",
        (
            OnlyFeeRule(
                "generic-notional-rate",
                OnlyFeeType.EXCHANGE_FEE,
                OnlyFeeAuthority.MARKET,
                OnlyFeeEconomicDirection.CHARGE,
                OnlyFeeFormula((OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, Decimal("0.001")),)),
                OnlyFeeCalculationScope.FILL,
                OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
                None,
                None,
                None,
                None,
                None,
                OnlyFeeRoundingPolicy(Decimal("0.01"), OnlyFeeRoundingMode.HALF_EVEN),
                OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
            ),
        ),
        market,
        None,
        "CASH",
    )
    return OnlyMarketFeePack.create(
        pack_id=pack_id,
        pack_version="1",
        compatible_market_profiles=(profile_id,),
        schedules=(schedule,),
    )


def only_generic_t0_cash_fee_pack() -> OnlyMarketFeePack:
    return _cash_pack(
        pack_id="GENERIC_T0_MARKET_FEE_PACK_CONFORMANCE",
        profile_id="GENERIC_T0_CASH",
        market="GENERIC",
    )


def only_cn_a_share_conformance_fee_pack() -> OnlyMarketFeePack:
    return _cash_pack(
        pack_id="CN_A_SHARE_TEST_MARKET_FEE_PACK",
        profile_id="CN_A_SHARE_CASH",
        market="CN_A_SHARE",
    )


__all__ = ["only_cn_a_share_conformance_fee_pack", "only_generic_t0_cash_fee_pack"]
