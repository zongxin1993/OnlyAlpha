from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlyRuntimePersistenceStorePort,
    OnlySqliteRuntimePersistenceStore,
)
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction


@pytest.fixture(params=("memory", "sqlite"))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[OnlyRuntimePersistenceStorePort]:
    selected: OnlyRuntimePersistenceStorePort
    if request.param == "memory":
        selected = OnlyInMemoryRuntimePersistenceStore()
    else:
        selected = OnlySqliteRuntimePersistenceStore(tmp_path / "ready-query.sqlite3")
    yield selected
    if isinstance(selected, OnlySqliteRuntimePersistenceStore):
        selected.close()


def _timestamp(second: int) -> OnlyTimestamp:
    return OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=second))


def _populate(store: OnlyRuntimePersistenceStorePort, runtime_id: OnlyRuntimeId) -> None:
    for sequence in range(1, 5):
        prepared = only_test_generic_t0_cash_buy_open_transaction(
            runtime_id=runtime_id,
            trade_id=OnlyTradeId(f"trade-{runtime_id}-{sequence}"),
            update_id=type(only_test_generic_t0_cash_buy_open_transaction().broker_update_id)(
                f"update-{runtime_id}-{sequence}"
            ),
        )
        store.commit(prepared, committed_at=_timestamp(sequence))
    store.mark_projection_ready(runtime_id, 1, projected_at=_timestamp(11))
    store.mark_projection_failed(runtime_id, 2, failed_at=_timestamp(12), error="injected")
    store.mark_projection_ready(runtime_id, 4, projected_at=_timestamp(14))


def test_ready_query_is_distinct_from_admin_and_projection_state_queries(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    _populate(store, runtime_id)

    assert tuple(item.execution_sequence for item in store.records(runtime_id)) == (1, 2, 3, 4)
    assert tuple(item.execution_sequence for item in store.unprojected(runtime_id)) == (2, 3)
    assert tuple(item.execution_sequence for item in store.ready_records(runtime_id)) == (1, 4)
    assert store.ready_count(runtime_id) == 2
    assert {item.key.execution_sequence for item in store.pending(runtime_id, limit=100)} == {1, 4}


def test_ready_query_runtime_scope_after_sequence_and_global_order(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    _populate(store, runtime_id)

    assert tuple(item.execution_sequence for item in store.ready_records(runtime_id, after_sequence=1)) == (4,)
    assert store.ready_count(runtime_id) == 2
    assert store.ready_records(OnlyRuntimeId("other-runtime")) == ()
    assert store.ready_count(OnlyRuntimeId("other-runtime")) == 0
    assert tuple((str(item.runtime_id), item.execution_sequence) for item in store.ready_records()) == (
        ("runtime", 1),
        ("runtime", 4),
    )


def test_sqlite_ready_state_payload_and_hash_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ready-restart.sqlite3"
    runtime_id = OnlyRuntimeId("runtime")
    first = OnlySqliteRuntimePersistenceStore(path)
    _populate(first, runtime_id)
    expected = first.ready_records(runtime_id)
    first.close()

    reopened = OnlySqliteRuntimePersistenceStore(path)
    try:
        actual = reopened.ready_records(runtime_id)
        assert actual == expected
        assert tuple(item.committed_payload_hash for item in actual) == tuple(
            item.committed_payload_hash for item in expected
        )
        assert reopened.ready_count(runtime_id) == 2
    finally:
        reopened.close()
