import sqlite3
from pathlib import Path

import pytest

from onlyalpha.execution import (
    ONLY_EXECUTION_STORE_SCHEMA_VERSION,
    OnlyExecutionStoreMetadataCorrupt,
    OnlyExecutionStoreSchemaUnsupported,
    OnlySqliteExecutionTransactionStore,
)


def test_sqlite_store_writes_and_validates_schema_metadata(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    store = OnlySqliteExecutionTransactionStore(path, identity={"runtime_id": "runtime"})
    assert store.metadata()["schema_version"] == ONLY_EXECUTION_STORE_SCHEMA_VERSION
    assert store.metadata()["runtime_id"] == "runtime"
    assert store.metadata()["created_at"]
    store.close()

    reopened = OnlySqliteExecutionTransactionStore(path, identity={"runtime_id": "runtime"})
    reopened.close()


def test_unknown_schema_version_fails_without_overwriting_database(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    store = OnlySqliteExecutionTransactionStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE execution_store_metadata SET value='999' WHERE key='schema_version'")
    with pytest.raises(OnlyExecutionStoreSchemaUnsupported, match="EXECUTION_STORE_SCHEMA_UNSUPPORTED"):
        OnlySqliteExecutionTransactionStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM execution_store_metadata WHERE key='schema_version'"
        ).fetchone() == ("999",)


def test_missing_metadata_table_is_corruption_not_a_fresh_store(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    with pytest.raises(OnlyExecutionStoreMetadataCorrupt, match="EXECUTION_STORE_METADATA_CORRUPT"):
        OnlySqliteExecutionTransactionStore(path)
