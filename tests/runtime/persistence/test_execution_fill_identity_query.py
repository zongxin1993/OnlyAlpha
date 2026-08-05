import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.execution import OnlyRuntimeTransactionConflict
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlySqliteRuntimePersistenceStore
from tests.execution.factories.transaction_factory import (
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_rehash,
)


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_fill_identity_query_duplicate_and_conflict_survive_store_reopen(kind: str, tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = OnlyInMemoryRuntimePersistenceStore() if kind == "memory" else OnlySqliteRuntimePersistenceStore(path)
    first = only_test_generic_t0_cash_buy_open_transaction()
    committed = store.commit(first, committed_at=first.prepared_at).transaction
    assert store.get_by_fill_identity(first.runtime_id, first.fact_draft.fill_identity) == committed

    envelope = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("new-envelope-trade"),
        update_id=type(first.fact_draft.broker_update_id)("new-envelope-update"),
    )
    duplicate = only_test_rehash(
        envelope,
        fact_draft=replace(
            envelope.fact_draft,
            fill_identity=first.fact_draft.fill_identity,
            fill_payload_fingerprint=first.fact_draft.fill_payload_fingerprint,
        ),
    )
    assert not store.commit(duplicate, committed_at=duplicate.prepared_at).inserted
    conflict = only_test_rehash(
        envelope,
        fact_draft=replace(envelope.fact_draft, fill_identity=first.fact_draft.fill_identity),
    )
    with pytest.raises(OnlyRuntimeTransactionConflict, match="Fill identity"):
        store.commit(conflict, committed_at=conflict.prepared_at)
    if isinstance(store, OnlySqliteRuntimePersistenceStore):
        store.close()
        reopened = OnlySqliteRuntimePersistenceStore(path)
        assert reopened.get_by_fill_identity(first.runtime_id, first.fact_draft.fill_identity) is not None
        reopened.close()


def test_sqlite_does_not_add_a_fill_identity_table(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path)
    store.close()
    connection = sqlite3.connect(path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    assert "execution_fills" not in tables
