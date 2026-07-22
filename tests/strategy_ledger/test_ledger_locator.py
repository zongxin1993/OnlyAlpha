from decimal import Decimal

import pytest

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.strategy_ledger.exceptions import OnlyStrategyLedgerScopeError
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager

RUNTIME = OnlyRuntimeId("locator-runtime")
ACCOUNT = OnlyAccountId("locator-account")
CURRENCY = OnlyCurrency("CNY", 2)


def _manager(order: tuple[str, ...] = ("b", "a")) -> tuple[OnlyStrategyLedgerManager, OnlyStrategyLedgerLocator]:
    manager = OnlyStrategyLedgerManager(RUNTIME)
    for cluster_id in order:
        key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, OnlyClusterId(cluster_id), CURRENCY)
        manager.create_ledger(key, OnlyMoney(Decimal("500.00"), CURRENCY), OnlyTimestamp(0))
    return manager, OnlyStrategyLedgerLocator(manager)


def test_locator_resolves_complete_scope_independent_of_registration_and_sort_order() -> None:
    for order in (("b", "a"), ("a", "b")):
        manager, locator = _manager(order)
        for cluster_id in ("a", "b"):
            key = locator.require_key(
                runtime_id=RUNTIME,
                account_id=ACCOUNT,
                cluster_id=OnlyClusterId(cluster_id),
                currency=CURRENCY,
            )
            assert key.cluster_id == OnlyClusterId(cluster_id)
            assert locator.require_snapshot(
                runtime_id=RUNTIME,
                account_id=ACCOUNT,
                cluster_id=OnlyClusterId(cluster_id),
                currency=CURRENCY,
            ) == manager.require_snapshot(key)


@pytest.mark.parametrize(
    ("runtime_id", "account_id", "cluster_id", "currency"),
    (
        (OnlyRuntimeId("other"), ACCOUNT, OnlyClusterId("a"), CURRENCY),
        (RUNTIME, OnlyAccountId("other"), OnlyClusterId("a"), CURRENCY),
        (RUNTIME, ACCOUNT, OnlyClusterId("missing"), CURRENCY),
        (RUNTIME, ACCOUNT, OnlyClusterId("a"), OnlyCurrency("USD", 2)),
    ),
)
def test_locator_rejects_every_scope_mismatch(
    runtime_id: OnlyRuntimeId,
    account_id: OnlyAccountId,
    cluster_id: OnlyClusterId,
    currency: OnlyCurrency,
) -> None:
    _, locator = _manager()
    with pytest.raises((KeyError, OnlyStrategyLedgerScopeError)):
        locator.require_key(
            runtime_id=runtime_id,
            account_id=account_id,
            cluster_id=cluster_id,
            currency=currency,
        )


def test_duplicate_complete_scope_creation_fails() -> None:
    manager, _ = _manager(("a",))
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, OnlyClusterId("a"), CURRENCY)
    with pytest.raises(ValueError, match="scope already registered"):
        manager.create_ledger(key, OnlyMoney(Decimal("500.00"), CURRENCY), OnlyTimestamp(1))
