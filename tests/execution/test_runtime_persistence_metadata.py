import sqlite3
from pathlib import Path

import pytest

from onlyalpha.runtime.persistence.store import (
    ONLY_RUNTIME_PERSISTENCE_SCHEMA_VERSION,
    OnlyRuntimePersistenceMetadataCorrupt,
    OnlyRuntimePersistenceSchemaUnsupported,
    OnlySqliteRuntimePersistenceStore,
)


def test_sqlite_persistence_writes_and_validates_schema_metadata(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path, identity={"runtime_id": "runtime"})
    assert store.metadata()["schema_version"] == ONLY_RUNTIME_PERSISTENCE_SCHEMA_VERSION
    assert store.metadata()["runtime_id"] == "runtime"
    assert store.metadata()["created_at"]
    store.close()

    reopened = OnlySqliteRuntimePersistenceStore(path, identity={"runtime_id": "runtime"})
    reopened.close()


def test_unknown_schema_version_fails_without_overwriting_database(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE runtime_persistence_metadata SET value='999' WHERE key='schema_version'")
    with pytest.raises(OnlyRuntimePersistenceSchemaUnsupported, match="RUNTIME_PERSISTENCE_SCHEMA_UNSUPPORTED"):
        OnlySqliteRuntimePersistenceStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM runtime_persistence_metadata WHERE key='schema_version'"
        ).fetchone() == ("999",)


def test_missing_metadata_table_is_corruption_not_a_fresh_store(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    with pytest.raises(OnlyRuntimePersistenceMetadataCorrupt, match="RUNTIME_PERSISTENCE_METADATA_CORRUPT"):
        OnlySqliteRuntimePersistenceStore(path)
