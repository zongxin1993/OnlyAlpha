from decimal import Decimal

from onlyalpha.account import OnlyAccountConfig, OnlyAccountManager, OnlyAccountQueryService, OnlyAccountType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.views import OnlyAccountManagerRiskView


def test_account_risk_view_maps_only_immutable_account_snapshot_fields() -> None:
    runtime_id = OnlyRuntimeId("risk-view-runtime")
    account_id = OnlyAccountId("risk-view-account")
    currency = OnlyCurrency("CNY", 2)
    manager = OnlyAccountManager(runtime_id)
    manager.create_account(
        OnlyAccountConfig(
            runtime_id,
            account_id,
            "virtual",
            OnlyAccountType.CASH,
            currency,
            OnlyMoney(Decimal("100.00"), currency),
        ),
        OnlyTimestamp.from_unix_seconds(1),
    )

    snapshot = OnlyAccountManagerRiskView(OnlyAccountQueryService(manager)).snapshot(account_id)

    assert snapshot is not None and snapshot.allows_new_orders
    assert snapshot.available_balances == (OnlyMoney(Decimal("100.00"), currency),)
