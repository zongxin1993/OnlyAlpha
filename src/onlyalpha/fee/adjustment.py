"""Immutable component-attributed forward fee corrections."""

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.evidence import OnlyFeeReconciliationComponentIdentity
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.reconciliation_policy import OnlyFeeReconciliationPolicyIdentity


class OnlyFeeAdjustmentDirection(StrEnum):
    SUPPLEMENTAL_CHARGE = "SUPPLEMENTAL_CHARGE"
    REFUND = "REFUND"


class OnlyFeeDifferenceReason(StrEnum):
    REPORTED_VARIANCE = "REPORTED_VARIANCE"
    COMPONENT_MISMATCH = "COMPONENT_MISMATCH"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    UNKNOWN_COMPONENT = "UNKNOWN_COMPONENT"


@dataclass(frozen=True, slots=True)
class OnlyFeeAdjustment(OnlyDomainModel):
    schema_version = 3

    adjustment_id: str
    component_identity: OnlyFeeReconciliationComponentIdentity
    direction: OnlyFeeAdjustmentDirection
    amount: OnlyMoney
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId | None
    order_id: OnlyOrderId | None
    trade_id: OnlyTradeId | None
    scope: OnlyExternalFeeEvidenceScope
    evidence_id: str
    reconciliation_id: str
    policy_identity: OnlyFeeReconciliationPolicyIdentity
    reason: OnlyFeeDifferenceReason

    def __post_init__(self) -> None:
        if not all((self.adjustment_id.strip(), self.evidence_id.strip(), self.reconciliation_id.strip())):
            raise ValueError("fee adjustment identity cannot be empty")
        if self.amount.amount <= 0:
            raise ValueError("fee adjustment amount must be positive")


@dataclass(frozen=True, slots=True)
class OnlyUnallocatedExternalFeeState(OnlyDomainModel):
    account_id: OnlyAccountId
    cumulative_charges: OnlyMoney
    cumulative_refunds: OnlyMoney
    version: int

    def __post_init__(self) -> None:
        if self.version < 1 or self.cumulative_charges.currency != self.cumulative_refunds.currency:
            raise ValueError("unallocated external fee state is invalid")
        if self.cumulative_charges.amount < 0 or self.cumulative_refunds.amount < 0:
            raise ValueError("unallocated external fee totals cannot be negative")


__all__ = [name for name in globals() if name.startswith("Only")]
