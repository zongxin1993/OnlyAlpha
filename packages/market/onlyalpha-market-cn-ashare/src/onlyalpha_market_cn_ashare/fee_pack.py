"""Versioned production market-fee authority for ordinary CNY A-shares."""

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
    OnlyOrderSide,
)

PACK_ID = "CN_A_SHARE_PRODUCTION_MARKET_FEES"
PACK_VERSION = "2025.06.30"
CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM = date(2025, 6, 30)
_CNY = OnlyCurrency("CNY", 2)
_ROUNDING = OnlyFeeRoundingPolicy(Decimal("0.01"), OnlyFeeRoundingMode.HALF_UP)


def _rule(
    rule_id: str, fee_type: OnlyFeeType, authority: OnlyFeeAuthority, rate: str, side: OnlyOrderSide | None
) -> OnlyFeeRule:
    return OnlyFeeRule(
        rule_id,
        fee_type,
        authority,
        OnlyFeeEconomicDirection.CHARGE,
        OnlyFeeFormula((OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, Decimal(rate)),)),
        OnlyFeeCalculationScope.FILL,
        OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
        None,
        None,
        side,
        None,
        None,
        _ROUNDING,
        OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
    )


def _schedule(
    schedule_id: str, version: str, source: str, venue: str, rule: OnlyFeeRule, start: date, end: date | None = None
) -> OnlyMarketFeeSchedule:
    return OnlyMarketFeeSchedule(schedule_id, version, start, end, _CNY, source, (rule,), "CN_A_SHARE", venue, "CASH")


def only_cn_a_share_market_fee_pack() -> OnlyMarketFeePack:
    schedules: list[OnlyMarketFeeSchedule] = []
    for venue, name, transfer_source in (
        ("XSHG", "SSE", "CSDC:SSE-FEE-TABLE:2025-06-30"),
        ("XSHE", "SZSE", "CSDC:SZSE-FEE-TABLE:2025-06-30"),
    ):
        schedules.extend(
            (
                _schedule(
                    f"CN_A_SHARE_{name}_STAMP_DUTY",
                    "1",
                    "PRC-NPC:STAMP-TAX-LAW:2021",
                    venue,
                    _rule(
                        "ordinary-cny-a-share-sell-stamp-duty",
                        OnlyFeeType.STAMP_DUTY,
                        OnlyFeeAuthority.REGULATOR,
                        "0.001",
                        OnlyOrderSide.SELL,
                    ),
                    date(2022, 7, 1),
                    date(2023, 8, 28),
                ),
                _schedule(
                    f"CN_A_SHARE_{name}_STAMP_DUTY",
                    "2",
                    "MOF-STA:ANNOUNCEMENT-2023-39:1",
                    venue,
                    _rule(
                        "ordinary-cny-a-share-sell-stamp-duty",
                        OnlyFeeType.STAMP_DUTY,
                        OnlyFeeAuthority.REGULATOR,
                        "0.0005",
                        OnlyOrderSide.SELL,
                    ),
                    date(2023, 8, 28),
                ),
                _schedule(
                    f"CN_A_SHARE_{name}_TRANSFER_FEE",
                    "1",
                    transfer_source,
                    venue,
                    _rule(
                        "ordinary-cny-a-share-bilateral-transfer-fee",
                        OnlyFeeType.TRANSFER_FEE,
                        OnlyFeeAuthority.CLEARING,
                        "0.00001",
                        None,
                    ),
                    date(2025, 6, 30),
                ),
            )
        )
    return OnlyMarketFeePack.create(
        pack_id=PACK_ID,
        pack_version=PACK_VERSION,
        compatible_market_profiles=("CN_A_SHARE_CASH",),
        schedules=tuple(schedules),
    )


__all__ = [
    "CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM",
    "PACK_ID",
    "PACK_VERSION",
    "only_cn_a_share_market_fee_pack",
]
