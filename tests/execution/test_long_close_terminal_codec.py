import sqlite3
from pathlib import Path

import pytest

from onlyalpha.execution.codec import (
    only_decode_committed_execution_transaction,
    only_decode_prepared_execution_transaction,
    only_encode_committed_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from onlyalpha.execution.enums import OnlyExecutionOperationKind
from onlyalpha.execution.terminal_fact import OnlyCommittedTerminalExecutionFact
from onlyalpha.execution.terminal_planner import OnlyTerminalExecutionTransactionPlanner
from onlyalpha.execution.transaction import OnlyPreparedExecutionTransaction
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlyRuntimePersistenceSchemaUnsupported,
    OnlySqliteRuntimePersistenceStore,
)
from tests.execution.test_long_close_terminal_planner import _terminal_update


def _prepared_terminal() -> OnlyPreparedExecutionTransaction:
    environment, _, update = _terminal_update("CANCELLED")
    scope = environment.runtime.execution_processor._resolve_position_scope(update)
    assert scope is not None
    context = environment.runtime._build_terminal_execution_planning_context(
        update,
        environment.runtime.execution_processor._processing_sequence + 1,
        scope,
    )
    return OnlyTerminalExecutionTransactionPlanner().prepare(context)


def test_terminal_operation_codec_round_trip_has_no_trade_id() -> None:
    prepared = _prepared_terminal()
    encoded = only_encode_prepared_execution_transaction(prepared)
    decoded = only_decode_prepared_execution_transaction(encoded)

    assert decoded == prepared
    assert decoded.operation_kind is OnlyExecutionOperationKind.ORDER_TERMINAL
    assert decoded.trade_id is None
    assert decoded.terminal_identity is not None


@pytest.mark.parametrize("sqlite", [False, True])
def test_terminal_operation_store_round_trip_and_admin_query(tmp_path: Path, sqlite: bool) -> None:
    prepared = _prepared_terminal()
    path = tmp_path / "terminal.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path) if sqlite else OnlyInMemoryRuntimePersistenceStore()
    committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction

    assert (
        only_decode_committed_execution_transaction(only_encode_committed_execution_transaction(committed)) == committed
    )
    assert committed.trade_id is None
    assert isinstance(committed.fact, OnlyCommittedTerminalExecutionFact)
    assert store.get_by_terminal_identity(prepared.runtime_id, committed.fact.terminal_identity) == committed
    store.close()

    if sqlite:
        reopened = OnlySqliteRuntimePersistenceStore(path)
        assert reopened.get_by_terminal_identity(prepared.runtime_id, committed.fact.terminal_identity) == committed
        assert reopened.records(prepared.runtime_id) == (committed,)
        reopened.close()


def test_runtime_schema_two_is_rejected_without_migration_or_deletion(tmp_path: Path) -> None:
    path = tmp_path / "schema-two.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE runtime_persistence_metadata SET value='2' WHERE key='schema_version'")
        before_tables = tuple(
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )

    with pytest.raises(
        OnlyRuntimePersistenceSchemaUnsupported,
        match=r"expected='3', actual='2'",
    ):
        OnlySqliteRuntimePersistenceStore(path)

    with sqlite3.connect(path) as connection:
        after_tables = tuple(
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        schema = connection.execute(
            "SELECT value FROM runtime_persistence_metadata WHERE key='schema_version'"
        ).fetchone()
    assert after_tables == before_tables
    assert schema == ("2",)
