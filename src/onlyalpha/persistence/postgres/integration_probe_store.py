"""Immutable PostgreSQL authority for completed Integration Probe Attempts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from onlyalpha.application.integration_configuration import OnlyIntegrationError, OnlyIntegrationId
from onlyalpha.application.integration_probe import OnlyIntegrationProbeAttempt
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresIntegrationProbeStore:
    def __init__(
        self,
        dsn: str,
        *,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def insert_probe_attempt(self, attempt: OnlyIntegrationProbeAttempt) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(
                    "INSERT INTO integration_probe_attempt "
                    "(probe_attempt_id, integration_id, revision_fingerprint, type_id, "
                    "type_descriptor_fingerprint, probe_contract_fingerprint, "
                    "probe_configuration_fingerprint, runtime_configuration_fingerprint, "
                    "started_at, completed_at, overall_status, result_fingerprint, result_document) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        attempt.probe_attempt_id,
                        attempt.integration_id.value,
                        attempt.revision_fingerprint,
                        attempt.type_id,
                        attempt.type_descriptor_fingerprint,
                        attempt.probe_contract_fingerprint,
                        attempt.probe_configuration_fingerprint,
                        attempt.runtime_configuration_fingerprint,
                        attempt.started_at,
                        attempt.completed_at,
                        attempt.overall_status.value,
                        attempt.result_fingerprint,
                        Json(dict(attempt.result_document)),
                    ),
                )
        except psycopg.IntegrityError as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_PERSISTENCE_CONFLICT") from exc
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE") from exc

    def get_probe_attempt(self, probe_attempt_id: str) -> OnlyIntegrationProbeAttempt:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT probe_attempt_id::text, integration_id::text, revision_fingerprint, type_id, "
                    "type_descriptor_fingerprint, probe_contract_fingerprint, "
                    "probe_configuration_fingerprint, runtime_configuration_fingerprint, started_at, "
                    "completed_at, overall_status, result_fingerprint, result_document "
                    "FROM integration_probe_attempt WHERE probe_attempt_id = %s",
                    (probe_attempt_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE") from exc
        if row is None:
            raise OnlyIntegrationError("INTEGRATION_PROBE_ATTEMPT_NOT_FOUND")
        return self._restore(row)

    def list_probe_attempts(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationProbeAttempt, ...]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT probe_attempt_id::text, integration_id::text, revision_fingerprint, type_id, "
                    "type_descriptor_fingerprint, probe_contract_fingerprint, "
                    "probe_configuration_fingerprint, runtime_configuration_fingerprint, started_at, "
                    "completed_at, overall_status, result_fingerprint, result_document "
                    "FROM integration_probe_attempt WHERE integration_id = %s "
                    "ORDER BY completed_at DESC, probe_attempt_id DESC",
                    (integration_id.value,),
                ).fetchall()
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_PERSISTENCE_UNAVAILABLE") from exc
        return tuple(self._restore(row) for row in rows)

    def latest_probe_attempt(
        self,
        integration_id: OnlyIntegrationId,
        revision_fingerprint: str,
    ) -> OnlyIntegrationProbeAttempt | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT probe_attempt_id::text, integration_id::text, revision_fingerprint, type_id, "
                    "type_descriptor_fingerprint, probe_contract_fingerprint, "
                    "probe_configuration_fingerprint, runtime_configuration_fingerprint, started_at, "
                    "completed_at, overall_status, result_fingerprint, result_document "
                    "FROM integration_probe_attempt WHERE integration_id = %s AND revision_fingerprint = %s "
                    "ORDER BY completed_at DESC, probe_attempt_id DESC LIMIT 1",
                    (integration_id.value, revision_fingerprint),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_PROVIDER_UNAVAILABLE") from exc
        return None if row is None else self._restore(row)

    @staticmethod
    def _restore(row: Mapping[str, object]) -> OnlyIntegrationProbeAttempt:
        try:
            return OnlyIntegrationProbeAttempt.restore(
                probe_attempt_id=str(row["probe_attempt_id"]),
                integration_id=OnlyIntegrationId(str(row["integration_id"])),
                revision_fingerprint=str(row["revision_fingerprint"]),
                type_id=str(row["type_id"]),
                type_descriptor_fingerprint=str(row["type_descriptor_fingerprint"]),
                probe_contract_fingerprint=str(row["probe_contract_fingerprint"]),
                probe_configuration_fingerprint=cast(str | None, row["probe_configuration_fingerprint"]),
                runtime_configuration_fingerprint=str(row["runtime_configuration_fingerprint"]),
                started_at=cast(datetime, row["started_at"]),
                completed_at=cast(datetime, row["completed_at"]),
                overall_status=OnlyIntegrationProbeStatus(str(row["overall_status"])),
                result_fingerprint=str(row["result_fingerprint"]),
                result_document=cast(Mapping[str, object], row["result_document"]),
            )
        except (KeyError, TypeError, ValueError, OnlyIntegrationError) as exc:
            raise OnlyIntegrationError("INTEGRATION_PROBE_RESULT_CORRUPT") from exc


__all__ = ["OnlyPostgresIntegrationProbeStore"]
