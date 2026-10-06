"""Atomic PostgreSQL chart T1 authority using the global Product Command lock."""

from __future__ import annotations

from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.application.chart_calculation import (
    OnlyChartCalculationAdmissionOutcome,
    OnlyChartCalculationCatalogWitnessV1,
    OnlyChartCalculationError,
    OnlyChartCalculationOperationV1,
    OnlyChartCalculationRequestV1,
    only_normalize_chart_calculation,
    only_verify_chart_calculation_retry,
)
from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAuthorityError,
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandConflictError,
    only_verify_product_command_binding,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.run.model import OnlyResearchRunId

from .config import OnlyPostgresOperationalConnectionOptions
from .product_command_authority import OnlyPostgresProductCommandAuthority


def _operation_fingerprint(operation: OnlyChartCalculationOperationV1) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": operation.schema_version,
            "operation_id": operation.operation_id.value,
            "product_command_id": operation.product_command_id.value,
            "command_fingerprint": operation.command_fingerprint,
            "intent_fingerprint": operation.intent_fingerprint,
            "catalog_witness_fingerprint": operation.catalog_witness.fingerprint,
            "reserved_run_id": operation.reserved_run_id.value,
            "accepted_at": operation.accepted_at,
            "state": operation.state,
            "preparation_revision": operation.preparation_revision,
        }
    )


class OnlyPostgresChartCalculationAdmissionStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def load_verified(self, command_id: OnlyProductCommandId) -> OnlyChartCalculationOperationV1 | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                OnlyPostgresProductCommandAuthority.lock_command(connection, command_id)
                return self._load(connection, command_id)
        except psycopg.Error as exc:
            raise OnlyProductCommandAuthorityUnavailableError(command_id.value) from exc

    @staticmethod
    def _load(
        connection: psycopg.Connection[dict[str, object]], command_id: OnlyProductCommandId
    ) -> OnlyChartCalculationOperationV1 | None:
        authority = OnlyPostgresProductCommandAuthority
        try:
            admission = authority.load_admission_in_transaction(connection, command_id)
            receipt = authority.load_receipt_in_transaction(connection, command_id)
            row = connection.execute(
                "SELECT * FROM chart_calculation_operation WHERE product_command_id = %s OR operation_id = %s",
                (command_id.value, command_id.value),
            ).fetchall()
            reservations = connection.execute(
                """SELECT *, EXISTS(SELECT 1 FROM research_run WHERE run_id = r.run_id) AS run_exists
                   FROM research_run_id_reservation r WHERE owner_id = %s OR run_id = %s""",
                (command_id.value, str(row[0]["reserved_run_id"]) if row else None),
            ).fetchall()
            if admission is not None and admission.command_kind is not OnlyProductCommandKind.CREATE_CHART_CALCULATION:
                if (
                    row
                    or reservations
                    or (
                        receipt is not None
                        and receipt.outcome_ref.kind is OnlyProductCommandOutcomeKind.CHART_CALCULATION_OPERATION
                    )
                ):
                    raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
                raise OnlyProductCommandConflictError(command_id.value)
            if admission is None and receipt is None and not row and not reservations:
                return None
            if admission is None or receipt is None or len(row) != 1 or len(reservations) != 1:
                raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
            only_verify_product_command_binding(admission, receipt)
            value = row[0]
            operation = OnlyChartCalculationOperationV1(
                OnlyProductCommandId(str(value["operation_id"])),
                OnlyProductCommandId(str(value["product_command_id"])),
                cast(str, value["command_fingerprint"]),
                cast(str, value["intent_fingerprint"]),
                OnlyChartCalculationRequestV1(cast(str, value["intent_json"])),
                OnlyChartCalculationCatalogWitnessV1(cast(str, value["catalog_witness_json"])),
                OnlyResearchRunId(str(value["reserved_run_id"])),
                cast(datetime, value["accepted_at"]),
                cast(int, value["schema_version"]),
                cast(str, value["state"]),
                cast(int, value["preparation_revision"]),
            )
            reservation = reservations[0]
            if (
                operation.product_command_id != command_id
                or operation.command_fingerprint != admission.command_fingerprint
                or receipt.outcome_ref
                != OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.CHART_CALCULATION_OPERATION, command_id.value
                )
                or receipt.accepted_at != operation.accepted_at
                or value["catalog_witness_fingerprint"] != operation.catalog_witness.fingerprint
                or value["operation_fingerprint"] != _operation_fingerprint(operation)
                or str(reservation["run_id"]) != operation.reserved_run_id.value
                or str(reservation["owner_id"]) != operation.operation_id.value
                or reservation["owner_kind"] != "CHART_CALCULATION"
                or reservation["reserved_at"] != operation.accepted_at
                or reservation["schema_version"] != 1
                or reservation["run_exists"]
            ):
                raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
            return operation
        except OnlyProductCommandConflictError:
            raise
        except (OnlyProductCommandAuthorityError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT") from exc

    def admit_or_replay(
        self,
        command_id: OnlyProductCommandId,
        request: OnlyChartCalculationRequestV1,
        witness: OnlyChartCalculationCatalogWitnessV1,
        *,
        accepted_at: datetime,
    ) -> OnlyChartCalculationAdmissionOutcome:
        # A direct port retry also uses only the originally admitted normalization contract.
        existing = self.load_verified(command_id)
        if existing is not None:
            only_verify_chart_calculation_retry(request, existing)
            return OnlyChartCalculationAdmissionOutcome(existing, True)
        # No Catalog/Integration/Runtime calls occur here, including inside the transaction.
        intent = only_normalize_chart_calculation(request, witness, accepted_at)
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.lock_command(connection, command_id)
                existing = self._load(connection, command_id)
                if existing is not None:
                    only_verify_chart_calculation_retry(request, existing)
                    return OnlyChartCalculationAdmissionOutcome(existing, True)
                reserved = self._reserve_run_id(connection, command_id)
                operation = OnlyChartCalculationOperationV1(
                    command_id,
                    command_id,
                    intent.command_fingerprint,
                    intent.intent_fingerprint,
                    intent,
                    witness,
                    reserved,
                    accepted_at,
                )
                authority.insert_or_verify_admission(
                    connection,
                    OnlyProductCommandAdmissionV1(
                        command_id, OnlyProductCommandKind.CREATE_CHART_CALCULATION, operation.command_fingerprint
                    ),
                )
                connection.execute(
                    """INSERT INTO chart_calculation_operation
                    (operation_id, product_command_id, reserved_run_id, command_fingerprint,
                     intent_fingerprint, intent_json, catalog_witness_json, catalog_witness_fingerprint,
                     operation_fingerprint, accepted_at, schema_version, state, preparation_revision)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 'ADMITTED', 0)""",
                    (
                        command_id.value,
                        command_id.value,
                        reserved.value,
                        operation.command_fingerprint,
                        operation.intent_fingerprint,
                        intent.canonical_json,
                        witness.canonical_json,
                        witness.fingerprint,
                        _operation_fingerprint(operation),
                        accepted_at,
                    ),
                )
                connection.execute(
                    """INSERT INTO research_run_id_reservation
                       (run_id, owner_kind, owner_id, reserved_at, schema_version)
                       VALUES (%s, 'CHART_CALCULATION', %s, %s, 1)""",
                    (reserved.value, command_id.value, accepted_at),
                )
                authority.insert_verified_receipt(
                    connection,
                    OnlyProductCommandReceipt(
                        command_id,
                        OnlyProductCommandKind.CREATE_CHART_CALCULATION,
                        operation.command_fingerprint,
                        OnlyProductCommandOutcomeRef(
                            OnlyProductCommandOutcomeKind.CHART_CALCULATION_OPERATION, command_id.value
                        ),
                        accepted_at,
                    ),
                )
                verified = self._load(connection, command_id)
                if verified != operation:
                    raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
            return OnlyChartCalculationAdmissionOutcome(operation, False)
        except psycopg.Error as exc:
            # Commit acknowledgement can be lost. Only exact converged durable authority proves acceptance.
            existing = self.load_verified(command_id)
            if existing is not None:
                only_verify_chart_calculation_retry(request, existing)
                return OnlyChartCalculationAdmissionOutcome(existing, True)
            raise OnlyProductCommandAuthorityUnavailableError(command_id.value) from exc

    @staticmethod
    def _reserve_run_id(
        connection: psycopg.Connection[dict[str, object]], command_id: OnlyProductCommandId
    ) -> OnlyResearchRunId:
        # Existing Research writers do not take the chart reservation advisory lock.
        # Hold their insertion boundary through T1 commit so absence is not a racy snapshot.
        connection.execute("LOCK TABLE research_run IN SHARE MODE")
        for _ in range(128):
            candidate = OnlyResearchRunId.new()
            if candidate.value == command_id.value:
                continue
            # Serialize detected UUID collisions across distinct commands. No Run is inserted.
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (candidate.value,))
            occupied = connection.execute(
                """SELECT EXISTS(SELECT 1 FROM research_run WHERE run_id = %s)
                       OR EXISTS(SELECT 1 FROM chart_calculation_operation WHERE reserved_run_id = %s)
                       OR EXISTS(SELECT 1 FROM research_run_id_reservation WHERE run_id = %s) AS occupied""",
                (candidate.value, candidate.value, candidate.value),
            ).fetchone()
            if occupied is not None and not occupied["occupied"]:
                return candidate
        raise OnlyProductCommandAuthorityUnavailableError("Research Run reservation collision limit")
