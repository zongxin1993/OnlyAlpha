"""Architecture-only generic futures fee pack."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.formula import OnlyFeeFormula, OnlyFeePerUnitTerm
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


def only_generic_margin_futures_fee_pack() -> "OnlyFeePolicyPack":
    from onlyalpha.fee.packs import OnlyFeePolicyPack

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
        "FUTURE",
    )
    return OnlyFeePolicyPack.create(
        pack_id="GENERIC_MARGIN_FUTURES_CONFORMANCE",
        pack_version="1",
        compatible_market_profiles=("GENERIC_MARGIN_FUTURES",),
        market_schedules=(schedule,),
    )


__all__ = ["only_generic_margin_futures_fee_pack"]
