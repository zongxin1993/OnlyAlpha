"""Configured baseline USD-M commission; funding remains a separate cashflow."""

from datetime import date
from decimal import Decimal

from onlyalpha.domain.enums import OnlyCurrencyType
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


def only_binance_usdm_baseline_fee_pack(maker: Decimal, taker: Decimal) -> OnlyMarketFeePack:
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
        "BINANCE_USDM_CONFIGURED_BASELINE",
        "1",
        date(1970, 1, 1),
        None,
        OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO),
        "CONFIGURED_BASELINE",
        (rule("maker", OnlyFeeType.MAKER_FEE, maker), rule("taker", OnlyFeeType.TAKER_FEE, taker)),
        "BINANCE_USDM",
        "BINANCE",
        "DERIVATIVE",
    )
    return OnlyMarketFeePack.create(
        pack_id="BINANCE_USDM_CONFIGURED_BASELINE",
        pack_version="1",
        compatible_market_products=("BINANCE_USDM",),
        schedules=(schedule,),
    )


__all__ = ["only_binance_usdm_baseline_fee_pack"]
