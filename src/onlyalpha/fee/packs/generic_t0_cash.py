"""Architecture-only generic cash fee pack."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.formula import OnlyFeeFormula, OnlyFeeRateTerm
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

if TYPE_CHECKING:
    from onlyalpha.fee.packs import OnlyFeePolicyPack


def only_generic_t0_cash_fee_pack() -> "OnlyFeePolicyPack":
    from onlyalpha.fee.packs import OnlyFeePolicyPack

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
    return OnlyFeePolicyPack.create(
        pack_id="GENERIC_T0_CASH_CONFORMANCE",
        pack_version="1",
        compatible_market_profiles=("CN_A_SHARE_CASH", "GENERIC_T0_CASH"),
        market_schedules=(schedule,),
    )


__all__ = ["only_generic_t0_cash_fee_pack"]
