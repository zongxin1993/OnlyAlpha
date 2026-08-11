"""GENERIC_T0_CASH@1 Market Fee authority definition."""

from datetime import date
from decimal import Decimal

from onlyalpha.plugin.api import (
    OnlyCurrency,
    OnlyFeeAuthority,
    OnlyFeeCalculationBasis,
    OnlyFeeCalculationPipeline,
    OnlyFeeCalculationScope,
    OnlyFeeEconomicDirection,
    OnlyFeeFormula,
    OnlyFeeRateTerm,
    OnlyFeeResolutionPolicy,
    OnlyFeeRoundingMode,
    OnlyFeeRoundingPolicy,
    OnlyFeeRule,
    OnlyFeeType,
    OnlyMarketFeePack,
    OnlyMarketFeeSchedule,
)


def only_generic_t0_cash_market_fee_pack() -> OnlyMarketFeePack:
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
        "GENERIC",
        None,
        "CASH",
    )
    return OnlyMarketFeePack.create(
        pack_id="GENERIC_T0_MARKET_FEE_PACK_CONFORMANCE",
        pack_version="1",
        compatible_market_products=("GENERIC_T0_CASH",),
        schedules=(schedule,),
    )


__all__ = ["only_generic_t0_cash_market_fee_pack"]
