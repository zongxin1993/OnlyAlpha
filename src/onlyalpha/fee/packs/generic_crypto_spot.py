"""Architecture-only generic crypto maker/taker charge/rebate pack."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from onlyalpha.domain.enums import OnlyLiquiditySide
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


def only_generic_crypto_spot_fee_pack() -> "OnlyFeePolicyPack":
    from onlyalpha.fee.packs import OnlyFeePolicyPack

    def rule(
        rule_id: str, fee_type: OnlyFeeType, role: OnlyLiquiditySide, direction: OnlyFeeEconomicDirection, rate: str
    ) -> OnlyFeeRule:
        return OnlyFeeRule(
            rule_id,
            fee_type,
            OnlyFeeAuthority.VENUE,
            direction,
            OnlyFeeFormula((OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, Decimal(rate)),)),
            OnlyFeeCalculationScope.FILL,
            OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
            None,
            None,
            None,
            None,
            role,
            OnlyFeeRoundingPolicy(Decimal("0.00000001"), OnlyFeeRoundingMode.HALF_EVEN),
            OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
        )

    schedule = OnlyMarketFeeSchedule(
        "GENERIC_CRYPTO_SPOT_FEES",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("USDT", 8),
        "OnlyAlpha Generic Conformance",
        (
            rule(
                "generic-maker-rebate",
                OnlyFeeType.MAKER_FEE,
                OnlyLiquiditySide.MAKER,
                OnlyFeeEconomicDirection.REBATE,
                "0.0001",
            ),
            rule(
                "generic-taker-charge",
                OnlyFeeType.TAKER_FEE,
                OnlyLiquiditySide.TAKER,
                OnlyFeeEconomicDirection.CHARGE,
                "0.0005",
            ),
        ),
        "GENERIC",
        None,
        "CRYPTO_SPOT",
    )
    return OnlyFeePolicyPack.create(
        pack_id="GENERIC_CRYPTO_SPOT_CONFORMANCE",
        pack_version="1",
        compatible_market_profiles=("GENERIC_24X7_CRYPTO_SPOT",),
        market_schedules=(schedule,),
    )


__all__ = ["only_generic_crypto_spot_fee_pack"]
