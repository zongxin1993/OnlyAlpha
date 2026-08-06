"""Risk-increase gate created by durable fee reconciliation."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationRiskGateState(OnlyDomainModel):
    account_id: OnlyAccountId
    blocked: bool
    reason: str | None
    evidence_id: str | None
    reconciliation_id: str | None
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("fee reconciliation risk gate version must be positive")
        if self.blocked and not all((self.reason, self.evidence_id, self.reconciliation_id)):
            raise ValueError("blocked fee reconciliation gate requires complete authority")


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

    def require_order_allowed(self, account_id: OnlyAccountId, side: OnlyOrderSide, offset: OnlyOffset) -> None:
        state = self._states.get(account_id)
        if state is None or not state.blocked:
            return
        if side is OnlyOrderSide.SELL and offset is OnlyOffset.CLOSE:
            return
        raise ValueError("FEE_RECONCILIATION_TRADING_BLOCKED")

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 1,
            "states": [
                state.to_json() for state in sorted(self._states.values(), key=lambda item: str(item.account_id))
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("UNSUPPORTED_FEE_CHECKPOINT_SCHEMA")
        values = payload.get("states")
        if not isinstance(values, list):
            raise ValueError("fee reconciliation risk gate checkpoint is invalid")
        states = tuple(OnlyFeeReconciliationRiskGateState.from_json(str(value)) for value in values)
        if len({state.account_id for state in states}) != len(states):
            raise ValueError("fee reconciliation risk gate checkpoint contains duplicate accounts")
        self._states = {state.account_id: state for state in states}


__all__ = ["OnlyFeeReconciliationRiskGate", "OnlyFeeReconciliationRiskGateState"]
