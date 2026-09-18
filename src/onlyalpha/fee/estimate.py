"""Order fee estimate request assembled from durable fee domain vocabulary."""

from dataclasses import dataclass

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.fee import OnlyFeeBasisValues, OnlyFeeSubject, OnlyOrderFeePolicyBinding
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.fee.resolution import OnlyFeePolicyResolution


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeEstimateRequest:
    subject: OnlyFeeSubject
    side: OnlyOrderSide
    offset: OnlyOffset
    expected_basis: OnlyFeeBasisValues
    full_order_basis: OnlyFeeBasisValues
    expected_fill_count: int
    maximum_fill_count: int | None
    trading_day: OnlyTradingDay
    binding: OnlyOrderFeePolicyBinding
    policy_resolution: OnlyFeePolicyResolution

    def __post_init__(self) -> None:
        if self.expected_fill_count < 1:
            raise ValueError("expected fill count must be positive")
        if self.maximum_fill_count is not None and self.maximum_fill_count < self.expected_fill_count:
            raise ValueError("maximum fill count cannot be smaller than expected fill count")


__all__ = ["OnlyOrderFeeEstimateRequest"]
