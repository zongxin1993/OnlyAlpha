"""Attributable active-blocker risk gate for fee reconciliation."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.fee.adjustment import OnlyFeeDifferenceReason
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.models import only_fee_fingerprint
from onlyalpha.fee.reconciliation_policy import OnlyFeeReconciliationPolicyIdentity
from onlyalpha.risk.enums import OnlyOrderRiskChange


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationBlocker(OnlyDomainModel):
    schema_version = 2

    blocker_id: str
    account_id: OnlyAccountId
    evidence_family_fingerprint: str
    evidence_id: str
    reconciliation_id: str
    reason: OnlyFeeDifferenceReason
    scope: OnlyExternalFeeEvidenceScope
    policy_identity: OnlyFeeReconciliationPolicyIdentity
    created_at: OnlyTimestamp
    fingerprint: str

    def __post_init__(self) -> None:
        payload = (
            self.blocker_id,
            str(self.account_id),
            self.evidence_family_fingerprint,
            self.evidence_id,
            self.reconciliation_id,
            self.reason.value,
            self.scope.to_dict(),
            self.policy_identity.to_dict(),
            self.created_at.to_dict(),
        )
        if not self.blocker_id.strip() or self.fingerprint != only_fee_fingerprint(payload):
            raise ValueError("FEE_RECONCILIATION_BLOCKER_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        account_id: OnlyAccountId,
        evidence_family_fingerprint: str,
        evidence_id: str,
        reconciliation_id: str,
        reason: OnlyFeeDifferenceReason,
        scope: OnlyExternalFeeEvidenceScope,
        policy_identity: OnlyFeeReconciliationPolicyIdentity,
        created_at: OnlyTimestamp,
    ) -> "OnlyFeeReconciliationBlocker":
        blocker_id = only_fee_fingerprint((evidence_family_fingerprint, reconciliation_id, policy_identity.to_dict()))
        payload = (
            blocker_id,
            str(account_id),
            evidence_family_fingerprint,
            evidence_id,
            reconciliation_id,
            reason.value,
            scope.to_dict(),
            policy_identity.to_dict(),
            created_at.to_dict(),
        )
        return cls(
            blocker_id,
            account_id,
            evidence_family_fingerprint,
            evidence_id,
            reconciliation_id,
            reason,
            scope,
            policy_identity,
            created_at,
            only_fee_fingerprint(payload),
        )


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationRiskGateState(OnlyDomainModel):
    schema_version = 3

    account_id: OnlyAccountId
    active_blockers: tuple[OnlyFeeReconciliationBlocker, ...]
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("fee reconciliation risk gate version must be positive")
        ordered = tuple(sorted(self.active_blockers, key=lambda item: item.blocker_id))
        if ordered != self.active_blockers or len({item.blocker_id for item in ordered}) != len(ordered):
            raise ValueError("FEE_RECONCILIATION_BLOCKER_CONFLICT")
        if any(item.account_id != self.account_id for item in ordered):
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT")

    @property
    def blocked(self) -> bool:
        return bool(self.active_blockers)


class OnlyFeeReconciliationRiskGate:
    def __init__(self) -> None:
        self._states: dict[OnlyAccountId, OnlyFeeReconciliationRiskGateState] = {}

    def get(self, account_id: OnlyAccountId) -> OnlyFeeReconciliationRiskGateState | None:
        return self._states.get(account_id)

    def restore(self, state: OnlyFeeReconciliationRiskGateState) -> None:
        current = self._states.get(state.account_id)
        if current is not None and state.version < current.version:
            raise ValueError("fee reconciliation risk gate version cannot regress")
        self._states[state.account_id] = state

    def require_order_allowed(self, account_id: OnlyAccountId, risk_change: OnlyOrderRiskChange) -> None:
        state = self._states.get(account_id)
        if state is None or not state.blocked or risk_change is OnlyOrderRiskChange.RISK_REDUCING:
            return
        if risk_change is OnlyOrderRiskChange.UNKNOWN:
            raise ValueError("FEE_RECONCILIATION_RISK_CLASSIFICATION_UNKNOWN")
        raise ValueError("FEE_RECONCILIATION_TRADING_BLOCKED")

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 3,
            "states": [
                state.to_json() for state in sorted(self._states.values(), key=lambda item: str(item.account_id))
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 3:
            raise ValueError("UNSUPPORTED_FEE_CHECKPOINT_SCHEMA")
        values = payload.get("states")
        if not isinstance(values, list):
            raise ValueError("fee reconciliation risk gate checkpoint is invalid")
        states = tuple(OnlyFeeReconciliationRiskGateState.from_json(str(value)) for value in values)
        if len({state.account_id for state in states}) != len(states):
            raise ValueError("fee reconciliation risk gate checkpoint contains duplicate accounts")
        self._states = {state.account_id: state for state in states}


__all__ = [name for name in globals() if name.startswith("Only")]
