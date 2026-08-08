"""Trade fee target assessment request."""

from dataclasses import dataclass

from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.fee.models import (
    OnlyFeeBasisValues,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyOrderFeePolicyBinding,
)
from onlyalpha.fee.resolution import OnlyFeePolicyResolution


@dataclass(frozen=True, slots=True)
class OnlyTradeFeeAssessmentRequest:
    subject: OnlyFeeSubject
    trade_id: OnlyTradeId
    fill_basis: OnlyFeeBasisValues
    cumulative_order_basis: OnlyFeeBasisValues
    trading_day: OnlyTradingDay
    liquidity_role: OnlyLiquiditySide | None
    local_finality: OnlyLocalFeeFinality
    binding: OnlyOrderFeePolicyBinding
    policy_resolution: OnlyFeePolicyResolution


__all__ = ["OnlyTradeFeeAssessmentRequest"]
