from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.account import (
    OnlyAccountConfig,
    OnlyAccountManager,
    OnlyAccountReconciliationAction,
    OnlyAccountReconciliationService,
    OnlyAccountStatus,
    OnlyAccountType,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney

CNY = OnlyCurrency("CNY", 2)
NOW = OnlyTimestamp.from_unix_seconds(1)


def money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), CNY)


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    account_id: OnlyAccountId
    cash_balance: OnlyMoney
    available_cash: OnlyMoney
    frozen_cash: OnlyMoney
    equity: OnlyMoney
    snapshot_time: OnlyTimestamp


def test_broker_local_conflict_is_explicit_and_never_silently_overwrites_local_truth() -> None:
    runtime_id = OnlyRuntimeId("runtime-account")
    account_id = OnlyAccountId("account-main")
    manager = OnlyAccountManager(runtime_id)
    manager.create_account(
        OnlyAccountConfig(runtime_id, account_id, "virtual", OnlyAccountType.CASH, CNY, money("100.00")), NOW
    )

    result = OnlyAccountReconciliationService(manager).reconcile(
        BrokerAccountSnapshot(
            account_id,
            money("90.00"),
            money("90.00"),
            money("0.00"),
            money("90.00"),
            NOW,
        )
    )

    assert result.action is OnlyAccountReconciliationAction.BLOCK_ACCOUNT
    assert manager.require_snapshot(account_id).cash.cash_balance == money("100.00")
    assert manager.require_snapshot(account_id).status is OnlyAccountStatus.RECONCILING
