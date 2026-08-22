"""PostgreSQL adapter for Worker presence and read-only operational projections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from onlyalpha.research.execution.model import (
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.operations.model import (
    OnlyResearchOperationalSnapshot,
    OnlyResearchRunOperationalRecord,
    OnlyResearchWorkerPresence,
)
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from onlyalpha.research.run.model import OnlyResearchRunId

from .config import OnlyPostgresOperationalConnectionOptions
from .research_execution_store import _decode_attempt
from .research_run_store import OnlyPostgresResearchRunStore


class OnlyPostgresResearchOperationsStore:
    """Presence writes use server time; all diagnosis inputs are read in one transaction."""

    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def announce_worker(
        self, worker_instance_id: OnlyResearchWorkerInstanceId, *, service_version: str
    ) -> OnlyResearchWorkerPresence:
        if not service_version:
            raise ValueError("service_version is required")
        return self._presence_write(
            """
            INSERT INTO research_worker_presence
                (worker_instance_id, started_at, last_seen_at, service_version)
            VALUES (%s, clock_timestamp(), clock_timestamp(), %s)
            ON CONFLICT (worker_instance_id) DO UPDATE
            SET last_seen_at = clock_timestamp(), service_version = EXCLUDED.service_version
            RETURNING *
            """,
            (worker_instance_id.value, service_version),
        )

    def heartbeat_worker(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchWorkerPresence:
        return self._presence_write(
            """
            UPDATE research_worker_presence SET last_seen_at = clock_timestamp()
            WHERE worker_instance_id = %s
            RETURNING *
            """,
            (worker_instance_id.value,),
        )

    def mark_worker_draining(self, worker_instance_id: OnlyResearchWorkerInstanceId) -> OnlyResearchWorkerPresence:
        return self._presence_write(
            """
            UPDATE research_worker_presence
            SET last_seen_at = clock_timestamp(), draining_since = COALESCE(draining_since, clock_timestamp())
            WHERE worker_instance_id = %s
            RETURNING *
            """,
            (worker_instance_id.value,),
        )

    def load_operational_snapshot(
        self, *, run_id: OnlyResearchRunId | None = None, limit: int = 100
    ) -> OnlyResearchOperationalSnapshot:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("operational snapshot limit must be between 1 and 1000")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.isolation_level = IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                observed_row = connection.execute("SELECT clock_timestamp() AS observed_at").fetchone()
                assert observed_row is not None
                if run_id is None:
                    run_rows = connection.execute(
                        "SELECT * FROM research_run ORDER BY queued_at DESC, run_id DESC LIMIT %s", (limit,)
                    ).fetchall()
                else:
                    run_rows = connection.execute(
                        "SELECT * FROM research_run WHERE run_id = %s", (run_id.value,)
                    ).fetchall()
                run_ids = tuple(str(row["run_id"]) for row in run_rows)
                attempt_rows: list[Mapping[str, object]] = []
                if run_ids:
                    loaded = connection.execute(
                        "SELECT * FROM research_run_attempt WHERE run_id = ANY(%s) "
                        "ORDER BY run_id ASC, attempt_number ASC, attempt_id ASC",
                        (list(run_ids),),
                    ).fetchall()
                    attempt_rows = [cast(Mapping[str, object], item) for item in loaded]
                presence_rows = connection.execute(
                    "SELECT * FROM research_worker_presence "
                    "ORDER BY last_seen_at DESC, worker_instance_id ASC LIMIT 1000"
                ).fetchall()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research operational snapshot unavailable") from exc
        attempts = tuple(_decode_attempt(row) for row in attempt_rows)
        records = tuple(
            OnlyResearchRunOperationalRecord(
                OnlyPostgresResearchRunStore._decode(cast(Mapping[str, object], row)),
                tuple(item for item in attempts if item.run_id.value == str(row["run_id"])),
            )
            for row in run_rows
        )
        return OnlyResearchOperationalSnapshot(
            cast(datetime, observed_row["observed_at"]),
            tuple(_decode_presence(cast(Mapping[str, object], row)) for row in presence_rows),
            records,
        )

    def _presence_write(self, query: str, parameters: tuple[object, ...]) -> OnlyResearchWorkerPresence:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(query, parameters).fetchone()
                if row is None:
                    raise OnlyResearchRunStoreUnavailableError("Worker presence does not exist")
        except OnlyResearchRunStoreUnavailableError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Worker presence transaction unavailable") from exc
        return _decode_presence(cast(Mapping[str, object], row))


def _decode_presence(row: Mapping[str, object]) -> OnlyResearchWorkerPresence:
    return OnlyResearchWorkerPresence(
        OnlyResearchWorkerInstanceId(str(row["worker_instance_id"])),
        cast(datetime, row["started_at"]),
        cast(datetime, row["last_seen_at"]),
        str(row["service_version"]),
        cast(datetime | None, row["draining_since"]),
    )


__all__ = ["OnlyPostgresResearchOperationsStore"]
