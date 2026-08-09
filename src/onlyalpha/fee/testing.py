"""Testing-only Fee Authorities; never install these in production composition."""

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


def only_cn_a_share_conformance_fee_pack() -> OnlyMarketFeePack:
    schedule = OnlyMarketFeeSchedule(
        "CN_A_SHARE_TEST_FEES",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("CNY"),
        "OnlyAlpha Test Conformance",
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
        "CN_A_SHARE",
        None,
        "CASH",
    )
    return OnlyMarketFeePack.create(
        pack_id="CN_A_SHARE_TEST_MARKET_FEE_PACK",
        pack_version="1",
        compatible_market_profiles=("CN_A_SHARE_CASH",),
        schedules=(schedule,),
    )


__all__ = ["only_cn_a_share_conformance_fee_pack"]
