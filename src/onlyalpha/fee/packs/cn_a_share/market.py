"""Versioned production fees for ordinary CNY cash A-share trading."""

from datetime import date
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
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
from onlyalpha.fee.packs.cn_a_share.sources import CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID
from onlyalpha.fee.policy import OnlyFeeRule
from onlyalpha.fee.rounding import OnlyFeeRoundingPolicy
from onlyalpha.fee.schedules import OnlyMarketFeeSchedule

CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_ID = "CN_A_SHARE_PRODUCTION_MARKET_FEES"
CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_VERSION = "2025.06.30"
CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM = date(2025, 6, 30)

_CNY = OnlyCurrency("CNY", 2)
_CENT_HALF_UP = OnlyFeeRoundingPolicy(Decimal("0.01"), OnlyFeeRoundingMode.HALF_UP)


def _rate_rule(
    *,
    rule_id: str,
    fee_type: OnlyFeeType,
    authority: OnlyFeeAuthority,
    rate: str,
    side: OnlyOrderSide | None,
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
        _CENT_HALF_UP,
        OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
    )


def _schedule(
    *,
    schedule_id: str,
    version: str,
    source_id: str,
    venue: str,
    rule: OnlyFeeRule,
    effective_from: date,
    effective_to: date | None = None,
) -> OnlyMarketFeeSchedule:
    if source_id not in CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID:
        raise ValueError("MARKET_FEE_SOURCE_NOT_REGISTERED")
    return OnlyMarketFeeSchedule(
        schedule_id,
        version,
        effective_from,
        effective_to,
        _CNY,
        source_id,
        (rule,),
        "CN_A_SHARE",
        venue,
        "CASH",
    )


def only_cn_a_share_production_fee_pack() -> OnlyMarketFeePack:
    """Return the exact, immutable P3 production authority pack."""

    schedules: list[OnlyMarketFeeSchedule] = []
    for venue, venue_name, transfer_source in (
        ("XSHG", "SSE", "CSDC:SSE-FEE-TABLE:2025-06-30"),
        ("XSHE", "SZSE", "CSDC:SZSE-FEE-TABLE:2025-06-30"),
    ):
        schedules.extend(
            (
                _schedule(
                    schedule_id=f"CN_A_SHARE_{venue_name}_STAMP_DUTY",
                    version="1",
                    source_id="PRC-NPC:STAMP-TAX-LAW:2021",
                    venue=venue,
                    rule=_rate_rule(
                        rule_id="ordinary-cny-a-share-sell-stamp-duty",
                        fee_type=OnlyFeeType.STAMP_DUTY,
                        authority=OnlyFeeAuthority.REGULATOR,
                        rate="0.001",
                        side=OnlyOrderSide.SELL,
                    ),
                    effective_from=date(2022, 7, 1),
                    effective_to=date(2023, 8, 28),
                ),
                _schedule(
                    schedule_id=f"CN_A_SHARE_{venue_name}_STAMP_DUTY",
                    version="2",
                    source_id="MOF-STA:ANNOUNCEMENT-2023-39:1",
                    venue=venue,
                    rule=_rate_rule(
                        rule_id="ordinary-cny-a-share-sell-stamp-duty",
                        fee_type=OnlyFeeType.STAMP_DUTY,
                        authority=OnlyFeeAuthority.REGULATOR,
                        rate="0.0005",
                        side=OnlyOrderSide.SELL,
                    ),
                    effective_from=date(2023, 8, 28),
                ),
                _schedule(
                    schedule_id=f"CN_A_SHARE_{venue_name}_TRANSFER_FEE",
                    version="1",
                    source_id=transfer_source,
                    venue=venue,
                    rule=_rate_rule(
                        rule_id="ordinary-cny-a-share-bilateral-transfer-fee",
                        fee_type=OnlyFeeType.TRANSFER_FEE,
                        authority=OnlyFeeAuthority.CLEARING,
                        rate="0.00001",
                        side=None,
                    ),
                    effective_from=CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM,
                ),
            )
        )
    return OnlyMarketFeePack.create(
        pack_id=CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_ID,
        pack_version=CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_VERSION,
        compatible_market_profiles=("CN_A_SHARE_CASH",),
        schedules=tuple(schedules),
    )


__all__ = [
    "CN_A_SHARE_PRODUCTION_FEE_COVERAGE_FROM",
    "CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_ID",
    "CN_A_SHARE_PRODUCTION_MARKET_FEE_PACK_VERSION",
    "only_cn_a_share_production_fee_pack",
]
