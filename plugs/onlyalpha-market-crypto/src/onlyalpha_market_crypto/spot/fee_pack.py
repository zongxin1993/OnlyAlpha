"""Explicit configured-baseline fee pack; never account-actual authority."""

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


def only_binance_spot_baseline_fee_pack(maker: Decimal, taker: Decimal) -> OnlyMarketFeePack:
    rounding = OnlyFeeRoundingPolicy(Decimal("0.00000001"), OnlyFeeRoundingMode.HALF_EVEN)

    def rule(name: str, kind: OnlyFeeType, rate: Decimal) -> OnlyFeeRule:
        return OnlyFeeRule(
            name,
            kind,
            OnlyFeeAuthority.MARKET,
            OnlyFeeEconomicDirection.CHARGE,
            OnlyFeeFormula((OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, rate),)),
            OnlyFeeCalculationScope.FILL,
            OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
            None,
            None,
            None,
            None,
            None,
            rounding,
            OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
        )

    schedule = OnlyMarketFeeSchedule(
        "BINANCE_SPOT_CONFIGURED_BASELINE",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("USDT", 8),
        "CONFIGURED_BASELINE",
        (rule("maker", OnlyFeeType.MAKER_FEE, maker), rule("taker", OnlyFeeType.TAKER_FEE, taker)),
        "BINANCE_SPOT",
        "BINANCE",
        "CASH",
    )
    return OnlyMarketFeePack.create(
        pack_id="BINANCE_SPOT_CONFIGURED_BASELINE",
        pack_version="1",
        compatible_market_products=("BINANCE_SPOT",),
        schedules=(schedule,),
    )


__all__ = ["only_binance_spot_baseline_fee_pack"]
