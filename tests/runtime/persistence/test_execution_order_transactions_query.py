from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyOrderId, OnlyTradeId
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlySqliteRuntimePersistenceStore
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_order_transactions_are_sorted_by_fill_index_then_sequence(kind: str, tmp_path: Path) -> None:
    store = (
        OnlyInMemoryRuntimePersistenceStore()
        if kind == "memory"
        else OnlySqliteRuntimePersistenceStore(tmp_path / "runtime.sqlite3")
    )
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=type(first.fact_draft.broker_update_id)("update-2"),
        fill_index=2,
    )
    store.commit(first, committed_at=first.prepared_at)
    store.commit(second, committed_at=second.prepared_at)
    records = store.transactions_for_order(first.runtime_id, OnlyOrderId("order"))
    assert tuple(item.fact.fill_index for item in records) == (1, 2)
    assert store.transactions_for_order(first.runtime_id, OnlyOrderId("missing")) == ()
    assert store.latest_fill_for_order(first.runtime_id, OnlyOrderId("order")) == records[-1]
    if isinstance(store, OnlySqliteRuntimePersistenceStore):
        store.close()
