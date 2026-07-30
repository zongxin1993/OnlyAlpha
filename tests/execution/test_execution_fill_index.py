from dataclasses import replace

import pytest

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import OnlyExecutionTransactionConflict
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from tests.execution.factories.transaction_factory import (
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_rehash,
)


def test_fill_index_is_per_order_contiguous_and_conflict_checked() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=type(first.broker_update_id)("update-2"),
        fill_index=2,
    )
    store.commit(first, committed_at=first.prepared_at)
    store.commit(second, committed_at=second.prepared_at)
    assert tuple(
        item.fact.fill_index for item in store.transactions_for_order(first.runtime_id, first.fact_draft.order_id)
    ) == (
        1,
        2,
    )
    conflict = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-conflict"),
        update_id=type(first.broker_update_id)("update-conflict"),
        fill_index=2,
    )
    with pytest.raises(OnlyExecutionTransactionConflict, match="Fill index"):
        store.commit(conflict, committed_at=conflict.prepared_at)
    assert store.latest_fill_for_order(first.runtime_id, first.fact_draft.order_id).fact.fill_index == 2  # type: ignore[union-attr]


def test_duplicate_fill_does_not_advance_index_or_sequence() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first = only_test_generic_t0_cash_buy_open_transaction()
    committed = store.commit(first, committed_at=first.prepared_at).transaction
    envelope = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("other-envelope-trade"),
        update_id=type(first.broker_update_id)("other-envelope-update"),
    )
    duplicate = only_test_rehash(
        envelope,
        fact_draft=replace(
            envelope.fact_draft,
            fill_identity=first.fact_draft.fill_identity,
            fill_payload_fingerprint=first.fact_draft.fill_payload_fingerprint,
        ),
    )
    result = store.commit(duplicate, committed_at=OnlyTimestamp(first.prepared_at.unix_nanos + 1))
    assert not result.inserted and result.transaction == committed
    assert len(store.records(first.runtime_id)) == 1
