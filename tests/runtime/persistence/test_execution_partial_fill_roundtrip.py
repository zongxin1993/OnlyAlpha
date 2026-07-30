import hashlib
import json
import sqlite3
from pathlib import Path

from onlyalpha.execution import only_encode_committed_execution_transaction
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction

_FILL_FIELDS = {
    "fill_identity",
    "fill_payload_fingerprint",
    "fill_index",
    "fill_count_after",
    "terminal_fill",
    "cumulative_price_quantity_after",
}


def test_sqlite_roundtrip_preserves_new_fill_authority(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlySqliteRuntimePersistenceStore(path)
    expected = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    store.close()
    reopened = OnlySqliteRuntimePersistenceStore(path)
    actual = reopened.get_by_sequence(prepared.runtime_id, 1)
    assert actual == expected
    assert actual is not None and actual.fact.fill_index == 1
    reopened.close()


def test_sqlite_query_reads_legacy_whole_fill_committed_payload_without_schema_migration(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlySqliteRuntimePersistenceStore(path)
    transaction = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    store.close()
    payload = json.loads(only_encode_committed_execution_transaction(transaction))
    for field in _FILL_FIELDS:
        payload["fact"].pop(field)
    payload_without_hash = dict(payload)
    payload_without_hash.pop("committed_payload_hash")
    legacy_hash = hashlib.sha256(
        json.dumps(payload_without_hash, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload["committed_payload_hash"] = legacy_hash
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(
            "UPDATE execution_transactions SET committed_payload=?, committed_payload_hash=?",
            (encoded, legacy_hash),
        )
    connection.close()
    reopened = OnlySqliteRuntimePersistenceStore(path)
    restored = reopened.get_by_sequence(prepared.runtime_id, 1)
    assert restored is not None
    assert restored.fact.fill_index == restored.fact.fill_count_after == 1
    assert restored.fact.terminal_fill
    reopened.close()
