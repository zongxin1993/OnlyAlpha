"""PostgreSQL session guard for the single mutation-capable Product Kernel."""

from __future__ import annotations

from threading import Lock
from typing import cast

import psycopg

from onlyalpha.kernel.host import OnlyKernelAuthorityAlreadyHeld, OnlyKernelAuthorityError

KERNEL_AUTHORITY_LOCK_CLASS_ID = 1_329_199_301
KERNEL_AUTHORITY_LOCK_OBJECT_ID = 5


class OnlyPostgresKernelAuthorityGuard:
    """Hold one frozen two-key advisory lock on one dedicated PostgreSQL session."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: psycopg.Connection[object] | None = None
        self._lock = Lock()

    def acquire(self) -> None:
        with self._lock:
            if self._connection is not None:
                raise OnlyKernelAuthorityError("Product Kernel authority guard is already acquired")
            try:
                connection = psycopg.connect(self._dsn, autocommit=True)
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(%s, %s)",
                    (KERNEL_AUTHORITY_LOCK_CLASS_ID, KERNEL_AUTHORITY_LOCK_OBJECT_ID),
                ).fetchone()
                if row is None or cast(tuple[object, ...], row)[0] is not True:
                    connection.close()
                    raise OnlyKernelAuthorityAlreadyHeld()
                self._connection = connection
            except OnlyKernelAuthorityError:
                raise
            except psycopg.Error as exc:
                raise OnlyKernelAuthorityError("Product Kernel authority guard is unavailable") from exc

    def assert_held(self) -> None:
        with self._lock:
            connection = self._connection
            if connection is None:
                raise OnlyKernelAuthorityError("Product Kernel mutation authority is not held")
            try:
                row = connection.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
                    "AND classid = %s AND objid = %s AND granted"
                    ")",
                    (KERNEL_AUTHORITY_LOCK_CLASS_ID, KERNEL_AUTHORITY_LOCK_OBJECT_ID),
                ).fetchone()
            except psycopg.Error as exc:
                raise OnlyKernelAuthorityError("Product Kernel mutation authority was lost") from exc
            if row is None or cast(tuple[object, ...], row)[0] is not True:
                raise OnlyKernelAuthorityError("Product Kernel mutation authority was lost")

    def release(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is None:
                return
            try:
                row = connection.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (KERNEL_AUTHORITY_LOCK_CLASS_ID, KERNEL_AUTHORITY_LOCK_OBJECT_ID),
                ).fetchone()
                if row is None or cast(tuple[object, ...], row)[0] is not True:
                    raise OnlyKernelAuthorityError("Product Kernel mutation authority release failed")
            except psycopg.Error as exc:
                raise OnlyKernelAuthorityError("Product Kernel mutation authority release failed") from exc
            finally:
                connection.close()


__all__ = [name for name in globals() if name.startswith(("Only", "KERNEL_"))]
