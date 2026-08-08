"""Architecture-only generic futures fee pack."""

from datetime import date
from decimal import Decimal

from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.formula import OnlyFeeFormula, OnlyFeePerUnitTerm
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


def only_generic_margin_futures_fee_pack() -> OnlyMarketFeePack:
    schedule = OnlyMarketFeeSchedule(
        "GENERIC_FUTURES_FEES",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("CNY"),
        "OnlyAlpha Generic Conformance",
        (
            OnlyFeeRule(
                "generic-contract-fee",
                OnlyFeeType.CONTRACT_FEE,
                OnlyFeeAuthority.VENUE,
                OnlyFeeEconomicDirection.CHARGE,
                OnlyFeeFormula((OnlyFeePerUnitTerm(OnlyFeeCalculationBasis.CONTRACTS, Decimal("2")),)),
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
        "FUTURES",
    )
    return OnlyMarketFeePack.create(
        pack_id="GENERIC_MARGIN_FUTURES_MARKET_FEE_PACK_CONFORMANCE",
        pack_version="1",
        compatible_market_profiles=("GENERIC_MARGIN_FUTURES",),
        schedules=(schedule,),
    )


__all__ = ["only_generic_margin_futures_fee_pack"]
