"""Order fee estimate and reservation-safe funding plan."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.models import OnlyFeeAssessment, OnlyFeeBasisValues, OnlyFeeSubject, OnlyOrderFeePolicyBinding
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


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeEstimate(OnlyDomainModel):
    schema_version = 2

    expected: OnlyFeeAssessment
    maximum: OnlyFeeAssessment
    reservation_charge: OnlyMoney
    estimated_rebate: OnlyMoney
    assumptions_fingerprint: str

    def __post_init__(self) -> None:
        values = (
            self.expected.total_charges,
            self.expected.total_rebates,
            self.maximum.total_charges,
            self.maximum.total_rebates,
            self.reservation_charge,
            self.estimated_rebate,
        )
        if len({item.currency for item in values}) != 1:
            raise ValueError("fee estimate currency mismatch")
        if self.reservation_charge != self.maximum.total_charges:
            raise ValueError("fee reservation must equal maximum charges")


@dataclass(frozen=True, slots=True)
class OnlyOrderFundingPlan(OnlyDomainModel):
    order_id: OnlyOrderId
    principal_reservation: OnlyMoney
    fee_reservation: OnlyMoney
    total_reservation: OnlyMoney
    binding_fingerprint: str
    estimate_fingerprint: str

    def __post_init__(self) -> None:
        if self.principal_reservation.currency != self.fee_reservation.currency:
            raise ValueError("funding plan currency mismatch")
        if self.total_reservation != self.principal_reservation + self.fee_reservation:
            raise ValueError("funding plan total does not conserve principal and fee")


__all__ = ["OnlyOrderFeeEstimate", "OnlyOrderFeeEstimateRequest", "OnlyOrderFundingPlan"]
