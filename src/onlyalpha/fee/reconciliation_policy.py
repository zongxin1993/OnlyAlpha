"""Versioned governance authority for external fee reconciliation."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.models import only_fee_fingerprint


class OnlyFeeReconciliationAction(StrEnum):
    ADJUST = "ADJUST"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicyIdentity(OnlyDomainModel):
    schema_version = 2

    policy_id: str
    policy_version: str
    currency: OnlyCurrency
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip() or len(self.fingerprint) != 64:
            raise ValueError("fee reconciliation policy identity is invalid")


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicy(OnlyDomainModel):
    policy_id: str
    policy_version: str
    currency: OnlyCurrency
    materiality_threshold: OnlyMoney
    unknown_difference_action: OnlyFeeReconciliationAction
    incomplete_evidence_action: OnlyFeeReconciliationAction
    component_mismatch_action: OnlyFeeReconciliationAction
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.policy_version.strip():
            raise ValueError("fee reconciliation policy identity cannot be empty")
        if self.materiality_threshold.currency != self.currency:
            raise ValueError("FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH")
        if self.materiality_threshold.amount < 0:
            raise ValueError("fee reconciliation materiality threshold cannot be negative")
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        currency: OnlyCurrency,
        materiality_threshold: OnlyMoney,
        unknown_difference_action: OnlyFeeReconciliationAction,
        incomplete_evidence_action: OnlyFeeReconciliationAction,
        component_mismatch_action: OnlyFeeReconciliationAction,
    ) -> "OnlyFeeReconciliationPolicy":
        payload = (
            policy_id,
            policy_version,
            currency.to_dict(),
            materiality_threshold.to_dict(),
            unknown_difference_action.value,
            incomplete_evidence_action.value,
            component_mismatch_action.value,
        )
        return cls(
            policy_id,
            policy_version,
            currency,
            materiality_threshold,
            unknown_difference_action,
            incomplete_evidence_action,
            component_mismatch_action,
            only_fee_fingerprint(payload),
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.policy_id,
            self.policy_version,
            self.currency.to_dict(),
            self.materiality_threshold.to_dict(),
            self.unknown_difference_action.value,
            self.incomplete_evidence_action.value,
            self.component_mismatch_action.value,
        )

    @property
    def identity(self) -> OnlyFeeReconciliationPolicyIdentity:
        return OnlyFeeReconciliationPolicyIdentity(
            self.policy_id,
            self.policy_version,
            self.currency,
            self.fingerprint,
        )


class OnlyFeeReconciliationPolicyRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, OnlyCurrency], OnlyFeeReconciliationPolicy] = {}

    def register(self, policy: OnlyFeeReconciliationPolicy) -> None:
        key = (policy.policy_id, policy.policy_version, policy.currency)
        current = self._items.get(key)
        if current is not None:
            if current.fingerprint != policy.fingerprint:
                raise ValueError("FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT")
            raise ValueError("FEE_RECONCILIATION_POLICY_DUPLICATE_VERSION")
        self._items[key] = policy

    def require(
        self,
        policy_id: str,
        policy_version: str,
        currency: OnlyCurrency,
    ) -> OnlyFeeReconciliationPolicy:
        try:
            return self._items[(policy_id, policy_version, currency)]
        except KeyError as exc:
            raise ValueError("FEE_RECONCILIATION_POLICY_NOT_INSTALLED") from exc


def only_standard_fee_reconciliation_policy(currency: OnlyCurrency) -> OnlyFeeReconciliationPolicy:
    return OnlyFeeReconciliationPolicy.create(
        policy_id="STANDARD_FEE_RECONCILIATION",
        policy_version="1",
        currency=currency,
        materiality_threshold=OnlyMoney(Decimal("0.10"), currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.ADJUST,
    )


__all__ = [name for name in globals() if name.startswith("Only")]
