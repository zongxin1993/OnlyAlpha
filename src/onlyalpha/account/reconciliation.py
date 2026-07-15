"""Field-level Broker/local Account reconciliation without silent overwrite."""

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.account.enums import (
    OnlyAccountAuthority,
    OnlyAccountReconciliationAction,
    OnlyAccountReconciliationSeverity,
)
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney


class OnlyBrokerAccountSnapshotView(Protocol):
    @property
    def account_id(self) -> OnlyAccountId: ...

    @property
    def cash_balance(self) -> OnlyMoney: ...

    @property
    def available_cash(self) -> OnlyMoney: ...

    @property
    def frozen_cash(self) -> OnlyMoney: ...

    @property
    def equity(self) -> OnlyMoney: ...

    @property
    def snapshot_time(self) -> OnlyTimestamp: ...


@dataclass(frozen=True, slots=True)
class OnlyAccountDifference(OnlyDomainModel):
    field: str
    local_value: str
    broker_value: str
    authority: OnlyAccountAuthority


@dataclass(frozen=True, slots=True)
class OnlyAccountConflict(OnlyDomainModel):
    difference: OnlyAccountDifference
    severity: OnlyAccountReconciliationSeverity
    reason: str


@dataclass(frozen=True, slots=True)
class OnlyAccountReconciliationResult(OnlyDomainModel):
    account_id: OnlyAccountId
    local: OnlyAccountSnapshot
    differences: tuple[OnlyAccountDifference, ...]
    conflicts: tuple[OnlyAccountConflict, ...]
    severity: OnlyAccountReconciliationSeverity
    action: OnlyAccountReconciliationAction


class OnlyAccountAuthorityPolicy:
    def authority_for(self, field: str) -> OnlyAccountAuthority:
        if field in {"cash_balance", "equity"}:
            return OnlyAccountAuthority.BROKER
        if field in {"available_cash", "frozen_cash"}:
            return OnlyAccountAuthority.RECONCILED
        return OnlyAccountAuthority.LOCAL


class OnlyAccountReconciliationService:
    def __init__(
        self,
        manager: OnlyAccountManager,
        policy: OnlyAccountAuthorityPolicy | None = None,
    ) -> None:
        self._manager = manager
        self._policy = policy or OnlyAccountAuthorityPolicy()

    def reconcile(self, broker: OnlyBrokerAccountSnapshotView) -> OnlyAccountReconciliationResult:
        local = self._manager.require_snapshot(broker.account_id)
        fields = {
            "cash_balance": (local.cash.cash_balance, broker.cash_balance),
            "available_cash": (local.cash.available_cash, broker.available_cash),
            "frozen_cash": (local.cash.frozen_cash, broker.frozen_cash),
            "equity": (local.equity, broker.equity),
        }
        differences = tuple(
            OnlyAccountDifference(name, left.to_json(), right.to_json(), self._policy.authority_for(name))
            for name, (left, right) in fields.items()
            if left != right
        )
        conflicts = tuple(
            OnlyAccountConflict(
                item,
                (
                    OnlyAccountReconciliationSeverity.BLOCK_ACCOUNT
                    if item.field in {"cash_balance", "equity"}
                    else OnlyAccountReconciliationSeverity.WARNING
                ),
                "Broker/local Account values differ",
            )
            for item in differences
        )
        severity = max(
            (item.severity for item in conflicts),
            key=lambda item: list(OnlyAccountReconciliationSeverity).index(item),
            default=OnlyAccountReconciliationSeverity.INFO,
        )
        action = (
            OnlyAccountReconciliationAction.BLOCK_ACCOUNT
            if severity is OnlyAccountReconciliationSeverity.BLOCK_ACCOUNT
            else OnlyAccountReconciliationAction.REFRESH
            if differences
            else OnlyAccountReconciliationAction.NONE
        )
        if action is OnlyAccountReconciliationAction.BLOCK_ACCOUNT:
            self._manager.start_reconciliation(broker.account_id, broker.snapshot_time, "BROKER_LOCAL_ACCOUNT_CONFLICT")
        return OnlyAccountReconciliationResult(
            broker.account_id,
            self._manager.require_snapshot(broker.account_id),
            differences,
            conflicts,
            severity,
            action,
        )
