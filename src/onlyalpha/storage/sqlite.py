"""Small transactional SQLite storage implementation."""

import sqlite3
from pathlib import Path
from threading import RLock

from onlyalpha.storage.base import OnlyStorage


class OnlySqliteStorage(OnlyStorage):
    """Durable namespaced blobs with idempotent upsert semantics."""

    def __init__(self, path: Path | str) -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = RLock()
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS only_state (namespace TEXT NOT NULL, key TEXT NOT NULL, value BLOB NOT NULL, PRIMARY KEY(namespace, key))"
            )

    def put(self, namespace: str, key: str, value: bytes) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO only_state(namespace, key, value) VALUES (?, ?, ?) ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value",
                (namespace, key, value),
            )

    def get(self, namespace: str, key: str) -> bytes | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM only_state WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
            return None if row is None else bytes(row[0])

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM only_state WHERE namespace=? AND key=?", (namespace, key))
            return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()
