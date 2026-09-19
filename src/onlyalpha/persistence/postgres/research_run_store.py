"""Thin explicit-SQL PostgreSQL Research Run Store adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandConflictError,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.command.errors import OnlyResearchCancellationConflictError
from onlyalpha.research.command.model import OnlyResearchRunPageCursor
from onlyalpha.research.command.novelty_admission import (
    OnlyResearchNoveltyAdmissionSubjectV1,
    OnlyResearchNoveltyAdmissionV1,
    OnlyResearchNoveltyAdmissionV2,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.errors import (
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunRevisionConflictError,
    OnlyResearchRunStateConflictError,
    OnlyResearchRunStoreUnavailableError,
)
from onlyalpha.research.run.model import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .config import OnlyPostgresOperationalConnectionOptions
from .product_command_authority import OnlyPostgresProductCommandAuthority

_COLUMNS = (
    "run_id",
    "revision",
    "state",
    "specification_schema_version",
    "specification_fingerprint",
    "specification_payload",
    "admission_resolution_fingerprint",
    "queued_at",
    "started_at",
    "cancel_requested_at",
    "finished_at",
    "research_result_fingerprint",
    "artifact_content_fingerprint",
    "calculation_execution_evidence_fingerprints",
    "failure_phase",
    "failure_code",
    "failure_detail",
    "authoring_provenance",
    "strategy_research_composition_fingerprint",
)


def _insert_run_query(columns: tuple[str, ...] = _COLUMNS) -> sql.Composed:
    return sql.SQL("INSERT INTO research_run ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )


class OnlyPostgresResearchRunStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute("SELECT * FROM research_run WHERE run_id = %s", (run_id.value,)).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run load failed") from exc
        if row is None:
            raise OnlyResearchRunNotFoundError(str(run_id))
        return self._decode(cast(Mapping[str, object], row))

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        try:
            return OnlyPostgresProductCommandAuthority(self._dsn).load_verified_receipt(command_id)
        except OnlyProductCommandAuthorityUnavailableError as exc:
            raise OnlyResearchRunStoreUnavailableError("Product Command Receipt load failed") from exc

    def load_novelty_admission(
        self, command_id: OnlyProductCommandId
    ) -> OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2 | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM research_novelty_admission WHERE command_id = %s",
                    (command_id.value,),
                ).fetchone()
                members = (
                    ()
                    if row is None or int(cast(int, row["schema_version"])) == 1
                    else tuple(
                        connection.execute(
                            "SELECT * FROM research_novelty_admission_subject WHERE command_id = %s ORDER BY ordinal",
                            (command_id.value,),
                        ).fetchall()
                    )
                )
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Novelty Admission load failed") from exc
        if row is None:
            return None
        return self._decode_novelty_admission(cast(Mapping[str, object], row), members)

    def _create_queued_with_verified_novelty_admission(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
        admission: OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2,
        *,
        expected_source_frontier: int,
    ) -> OnlyProductCommandReceipt:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("submission requires revision-zero QUEUED Run")
        if (
            receipt.command_kind is not OnlyProductCommandKind.CREATE_RESEARCH_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
            or receipt.outcome_ref.outcome_id != run.run_id.value
            or receipt.accepted_at != run.queued_at
            or admission.command_id != receipt.command_id
            or admission.command_fingerprint != receipt.command_fingerprint
            or admission.run_id != run.run_id
        ):
            raise OnlyResearchRunIntegrityError("Novelty Admission does not bind the prepared Run and Receipt")
        run_query = _insert_run_query()
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.insert_or_verify_admission(
                    connection,
                    OnlyProductCommandAdmissionV1(
                        receipt.command_id,
                        receipt.command_kind,
                        receipt.command_fingerprint,
                    ),
                )
                existing = authority.load_verified_receipt_in_transaction(connection, receipt.command_id)
                if existing is not None:
                    return existing
                subjects = (
                    (admission.evaluation_subject_fingerprint,)
                    if isinstance(admission, OnlyResearchNoveltyAdmissionV1)
                    else tuple(item.evaluation_subject_fingerprint for item in admission.members)
                )
                guards = (
                    (admission.same_subject_guard_key,)
                    if isinstance(admission, OnlyResearchNoveltyAdmissionV1)
                    else tuple(item.same_subject_guard_key for item in admission.members)
                )
                for guard in guards:
                    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (guard,))
                frontier_row = connection.execute(
                    "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE FOR UPDATE"
                ).fetchone()
                if frontier_row is None:
                    raise OnlyResearchRunIntegrityError("Research source frontier is missing")
                current_frontier = int(cast(int, frontier_row["last_index"]))
                if current_frontier < expected_source_frontier or self._has_relevant_source_change(
                    connection, expected_source_frontier, subjects
                ):
                    raise OnlyResearchRunIntegrityError("NOVELTY_DECISION_STALE")
                existing = authority.load_verified_receipt_in_transaction(connection, receipt.command_id)
                if existing is not None:
                    return existing
                # ponytail: legacy Runs have no canonical subject witness, so one
                # active legacy Run blocks V3 admission until legacy work drains.
                legacy = connection.execute(
                    "SELECT 1 FROM research_run AS run "
                    "LEFT JOIN research_novelty_admission AS gated ON gated.run_id = run.run_id "
                    "WHERE run.state IN ('QUEUED', 'RUNNING') AND gated.run_id IS NULL LIMIT 1"
                ).fetchone()
                if legacy is not None:
                    raise OnlyResearchRunIntegrityError("NOVELTY_UNCLASSIFIED_RESEARCH_IN_FLIGHT")
                conflict = connection.execute(
                    "SELECT 1 FROM research_novelty_admission AS gated "
                    "JOIN research_run AS run ON run.run_id = gated.run_id "
                    "LEFT JOIN research_novelty_admission_subject AS member "
                    "ON member.command_id = gated.command_id "
                    "WHERE (gated.evaluation_subject_fingerprint = ANY(%s) "
                    "OR member.evaluation_subject_fingerprint = ANY(%s)) "
                    "AND run.state IN ('QUEUED', 'RUNNING') LIMIT 1",
                    (list(subjects), list(subjects)),
                ).fetchone()
                if conflict is not None:
                    raise OnlyResearchRunIntegrityError("NOVELTY_SAME_SUBJECT_IN_FLIGHT")
                connection.execute(run_query, self._values(run))
                self._insert_novelty_admission(connection, admission)
                self._insert_receipt(connection, receipt)
            return receipt
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchRunIntegrityError(
                f"Product Command identity already exists: {receipt.command_id}"
            ) from exc
        except (OnlyResearchRunIntegrityError, OnlyResearchRunStateConflictError):
            raise
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(receipt.command_id)
            if existing is not None:
                return existing
            raise OnlyResearchRunIntegrityError("Novelty Admission identity already exists") from exc
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Novelty-gated Research transaction failed") from exc

    @staticmethod
    def _has_relevant_source_change(
        connection: psycopg.Connection[dict[str, object]],
        expected_frontier: int,
        subjects: tuple[str, ...],
    ) -> bool:
        relations = connection.execute(
            "SELECT DISTINCT gated.run_id::text AS run_id, gated.command_id::text AS command_id "
            "FROM research_novelty_admission AS gated "
            "LEFT JOIN research_novelty_admission_subject AS member ON member.command_id = gated.command_id "
            "WHERE gated.evaluation_subject_fingerprint = ANY(%s) "
            "OR member.evaluation_subject_fingerprint = ANY(%s)",
            (list(subjects), list(subjects)),
        ).fetchall()
        run_ids = {str(item["run_id"]) for item in relations}
        command_ids = {str(item["command_id"]) for item in relations}
        classified_run_ids = {
            str(item["run_id"])
            for item in connection.execute("SELECT run_id::text AS run_id FROM research_novelty_admission").fetchall()
        }
        for event in connection.execute(
            "SELECT source_family, native_locator, source_row FROM research_source_history "
            "WHERE event_index > %s ORDER BY event_index",
            (expected_frontier,),
        ).fetchall():
            family = str(event["source_family"])
            locator = str(event["native_locator"])
            source_row = event["source_row"]
            if family == "RESEARCH_RUN" and (locator in run_ids or locator not in classified_run_ids):
                return True
            if family == "RESEARCH_ATTEMPT" and isinstance(source_row, Mapping):
                run_id = source_row.get("run_id")
                if run_id in run_ids or run_id not in classified_run_ids:
                    return True
            if family in {"PRODUCT_COMMAND_ADMISSION", "PRODUCT_COMMAND_RECEIPT"} and locator in command_ids:
                return True
        return False

    @staticmethod
    def _insert_novelty_admission(
        connection: psycopg.Connection[dict[str, object]],
        admission: OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2,
    ) -> None:
        if isinstance(admission, OnlyResearchNoveltyAdmissionV1):
            connection.execute(
                "INSERT INTO research_novelty_admission ("
                "command_id, command_fingerprint, novelty_decision_fingerprint, "
                "canonical_intent_fingerprint, evaluation_subject_fingerprint, "
                "decision_time_proof_fingerprint, action_time_proof_fingerprint, "
                "action_source_manifest_fingerprint, same_subject_guard_key, "
                "runtime_work_id, run_id, admission_fingerprint, schema_version"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
                (
                    admission.command_id.value,
                    admission.command_fingerprint,
                    admission.novelty_decision_fingerprint,
                    admission.canonical_intent_fingerprint,
                    admission.evaluation_subject_fingerprint,
                    admission.decision_time_proof_fingerprint,
                    admission.action_time_proof_fingerprint,
                    admission.action_source_manifest_fingerprint,
                    admission.same_subject_guard_key,
                    admission.runtime_work_id,
                    admission.run_id.value,
                    admission.admission_fingerprint,
                ),
            )
            return
        connection.execute(
            "INSERT INTO research_novelty_admission ("
            "command_id, command_fingerprint, decision_group_fingerprint, subject_set_fingerprint, "
            "action_source_manifest_fingerprint, runtime_work_id, run_id, admission_fingerprint, schema_version"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 2)",
            (
                admission.command_id.value,
                admission.command_fingerprint,
                admission.decision_group_fingerprint,
                admission.subject_set_fingerprint,
                admission.action_source_manifest_fingerprint,
                admission.runtime_work_id,
                admission.run_id.value,
                admission.admission_fingerprint,
            ),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO research_novelty_admission_subject ("
                "command_id, admission_fingerprint, ordinal, evaluation_subject_fingerprint, "
                "novelty_decision_fingerprint, canonical_intent_fingerprint, "
                "decision_time_proof_fingerprint, action_time_proof_fingerprint, "
                "same_subject_guard_key, schema_version"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
                [
                    (
                        admission.command_id.value,
                        admission.admission_fingerprint,
                        member.ordinal,
                        member.evaluation_subject_fingerprint,
                        member.novelty_decision_fingerprint,
                        member.canonical_intent_fingerprint,
                        member.decision_time_proof_fingerprint,
                        member.action_time_proof_fingerprint,
                        member.same_subject_guard_key,
                    )
                    for member in admission.members
                ],
            )

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyResearchRunId,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt:
        if (
            receipt.command_kind is not OnlyProductCommandKind.CANCEL_RESEARCH_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
            or receipt.outcome_ref.outcome_id != run_id.value
        ):
            raise OnlyResearchRunIntegrityError("Cancel Research Run receipt does not bind the target Run")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.insert_or_verify_admission(
                    connection,
                    OnlyProductCommandAdmissionV1(
                        receipt.command_id,
                        receipt.command_kind,
                        receipt.command_fingerprint,
                    ),
                )
                existing = authority.load_verified_receipt_in_transaction(connection, receipt.command_id)
                if existing is not None:
                    return existing
                row = connection.execute(
                    "SELECT * FROM research_run WHERE run_id = %s FOR UPDATE",
                    (run_id.value,),
                ).fetchone()
                if row is None:
                    raise OnlyResearchRunNotFoundError(str(run_id))
                current = self._decode(cast(Mapping[str, object], row))
                if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
                    raise OnlyResearchCancellationConflictError()
                if current.state not in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
                    target = (
                        OnlyResearchRunState.CANCELLED
                        if current.state is OnlyResearchRunState.QUEUED
                        else OnlyResearchRunState.CANCEL_REQUESTED
                    )
                    transitioned = current.transition(target, at=receipt.accepted_at)
                    assignments = tuple(name for name in _COLUMNS if name != "run_id")
                    query = sql.SQL(
                        "UPDATE research_run SET {} WHERE run_id = %s AND revision = %s AND state = %s"
                    ).format(
                        sql.SQL(", ").join(
                            sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()])
                            for name in assignments
                        )
                    )
                    values = self._values(transitioned)
                    parameters = tuple(values[_COLUMNS.index(name)] for name in assignments) + (
                        current.run_id.value,
                        current.revision,
                        current.state.value,
                    )
                    if connection.execute(query, parameters).rowcount != 1:
                        raise OnlyResearchRunRevisionConflictError(
                            f"Run {current.run_id} revision/state changed concurrently"
                        )
                self._insert_receipt(connection, receipt)
            return receipt
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchRunIntegrityError(
                f"Product Command identity already exists: {receipt.command_id}"
            ) from exc
        except (OnlyResearchCancellationConflictError, OnlyResearchRunNotFoundError):
            raise
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(receipt.command_id)
            if existing is None:
                raise OnlyResearchRunIntegrityError("Product Command identity conflict has no authority") from exc
            return existing
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Cancel Research Run transaction failed") from exc

    def list_recent(self, *, limit: int, after: OnlyResearchRunPageCursor | None = None) -> tuple[OnlyResearchRun, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Research Run list limit must be positive")
        query = "SELECT * FROM research_run"
        parameters: tuple[object, ...]
        if after is None:
            parameters = (limit,)
        else:
            query += " WHERE (queued_at, run_id) < (%s, %s)"
            parameters = (after.queued_at, after.run_id.value, limit)
        query += " ORDER BY queued_at DESC, run_id DESC LIMIT %s"
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(query, parameters).fetchall()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run list failed") from exc
        return tuple(self._decode(cast(Mapping[str, object], row)) for row in rows)

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun:
        if not transitioned.is_exact_successor_of(previous):
            raise OnlyResearchRunStateConflictError("Store accepts only an exact Domain-validated successor")
        allowed_command = (
            previous.state is OnlyResearchRunState.QUEUED and transitioned.state is OnlyResearchRunState.CANCELLED
        ) or (
            previous.state is OnlyResearchRunState.RUNNING
            and transitioned.state is OnlyResearchRunState.CANCEL_REQUESTED
        )
        if not allowed_command:
            raise OnlyResearchRunStateConflictError(
                "Claim and execution outcomes require the fenced Research Execution Store"
            )

        def update(columns: tuple[str, ...]) -> OnlyResearchRun:
            assignments = tuple(name for name in columns if name != "run_id")
            query = sql.SQL("UPDATE research_run SET {} WHERE run_id = %s AND revision = %s AND state = %s").format(
                sql.SQL(", ").join(
                    sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()]) for name in assignments
                )
            )
            values = self._values(transitioned)
            parameters = tuple(values[_COLUMNS.index(name)] for name in assignments) + (
                previous.run_id.value,
                previous.revision,
                previous.state.value,
            )
            with psycopg.connect(self._dsn) as connection:
                cursor = connection.execute(query, parameters)
                if cursor.rowcount != 1:
                    raise OnlyResearchRunRevisionConflictError(
                        f"Run {previous.run_id} revision/state changed concurrently"
                    )
            return transitioned

        try:
            return update(_COLUMNS)
        except OnlyResearchRunRevisionConflictError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run transition transaction failed") from exc

    @staticmethod
    def _values(run: OnlyResearchRun) -> tuple[object, ...]:
        failure = run.failure
        return (
            run.run_id.value,
            run.revision,
            run.state.value,
            run.specification.schema_version,
            run.specification_fingerprint,
            run.canonical_specification_payload,
            run.admission_resolution_fingerprint,
            run.queued_at,
            run.started_at,
            run.cancel_requested_at,
            run.finished_at,
            run.research_result_fingerprint,
            run.artifact_content_fingerprint,
            list(run.calculation_execution_evidence_fingerprints),
            None if failure is None else failure.phase.value,
            None if failure is None else failure.code,
            None if failure is None else failure.detail,
            None if run.authoring_provenance is None else only_canonical_json(run.authoring_provenance.to_dict()),
            run.strategy_research_composition_fingerprint,
        )

    @staticmethod
    def _insert_receipt(connection: psycopg.Connection[object], receipt: OnlyProductCommandReceipt) -> None:
        OnlyPostgresProductCommandAuthority.insert_verified_receipt(connection, receipt)

    @staticmethod
    def _decode_receipt(row: Mapping[str, object]) -> OnlyProductCommandReceipt:
        try:
            return OnlyProductCommandReceipt(
                command_id=OnlyProductCommandId(str(row["command_id"])),
                command_kind=OnlyProductCommandKind(str(row["command_kind"])),
                command_fingerprint=str(row["command_fingerprint"]),
                outcome_ref=OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind(str(row["outcome_kind"])),
                    str(row["outcome_id"]),
                ),
                accepted_at=cast(datetime, row["accepted_at"]),
                schema_version=int(cast(int, row["schema_version"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchRunIntegrityError(
                "PostgreSQL Product Command Receipt row failed strict verification"
            ) from exc

    @staticmethod
    def _decode_novelty_admission(
        row: Mapping[str, object], members: tuple[Mapping[str, object], ...] = ()
    ) -> OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2:
        try:
            schema = int(cast(int, row["schema_version"]))
            if schema == 1:
                value: OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2 = OnlyResearchNoveltyAdmissionV1(
                    OnlyProductCommandId(str(row["command_id"])),
                    str(row["command_fingerprint"]),
                    str(row["novelty_decision_fingerprint"]),
                    str(row["canonical_intent_fingerprint"]),
                    str(row["evaluation_subject_fingerprint"]),
                    str(row["decision_time_proof_fingerprint"]),
                    str(row["action_time_proof_fingerprint"]),
                    str(row["action_source_manifest_fingerprint"]),
                    str(row["same_subject_guard_key"]),
                    str(row["runtime_work_id"]),
                    OnlyResearchRunId(str(row["run_id"])),
                    schema,
                )
            elif schema == 2:
                value = OnlyResearchNoveltyAdmissionV2(
                    OnlyProductCommandId(str(row["command_id"])),
                    str(row["command_fingerprint"]),
                    str(row["decision_group_fingerprint"]),
                    str(row["subject_set_fingerprint"]),
                    str(row["action_source_manifest_fingerprint"]),
                    str(row["runtime_work_id"]),
                    OnlyResearchRunId(str(row["run_id"])),
                    tuple(
                        OnlyResearchNoveltyAdmissionSubjectV1(
                            int(cast(int, item["ordinal"])),
                            str(item["evaluation_subject_fingerprint"]),
                            str(item["novelty_decision_fingerprint"]),
                            str(item["canonical_intent_fingerprint"]),
                            str(item["decision_time_proof_fingerprint"]),
                            str(item["action_time_proof_fingerprint"]),
                            str(item["same_subject_guard_key"]),
                            int(cast(int, item["schema_version"])),
                        )
                        for item in members
                    ),
                    schema,
                )
            else:
                raise ValueError("Research Novelty Admission schema is unsupported")
            if row["admission_fingerprint"] != value.admission_fingerprint:
                raise ValueError("Admission fingerprint mismatch")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchRunIntegrityError(
                "PostgreSQL Research Novelty Admission row failed strict verification"
            ) from exc

    @staticmethod
    def _decode(row: Mapping[str, object]) -> OnlyResearchRun:
        try:
            raw = json.loads(str(row["specification_payload"]))
            if not isinstance(raw, dict):
                raise ValueError("Specification payload is not an object")
            specification = OnlyResearchSpecification.from_dict(raw)
            canonical = only_canonical_json(specification.to_dict())
            if canonical != row["specification_payload"]:
                raise ValueError("Specification payload is not exact canonical JSON")
            if specification.schema_version != row["specification_schema_version"]:
                raise ValueError("Specification schema version mismatch")
            failure = (
                None
                if row["failure_phase"] is None
                else OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase(str(row["failure_phase"])),
                    str(row["failure_code"]),
                    str(row["failure_detail"]),
                )
            )
            raw_evidence = row["calculation_execution_evidence_fingerprints"]
            if raw_evidence is None:
                evidence: tuple[str, ...] = ()
            elif isinstance(raw_evidence, list) and all(isinstance(item, str) for item in raw_evidence):
                evidence = tuple(cast(list[str], raw_evidence))
            else:
                raise ValueError("Execution Evidence references must be an array or null")
            return OnlyResearchRun(
                run_id=OnlyResearchRunId(str(row["run_id"])),
                revision=int(cast(int, row["revision"])),
                state=OnlyResearchRunState(str(row["state"])),
                specification=specification,
                specification_fingerprint=str(row["specification_fingerprint"]),
                canonical_specification_payload=canonical,
                admission_resolution_fingerprint=str(row["admission_resolution_fingerprint"]),
                queued_at=cast(datetime, row["queued_at"]),
                started_at=cast(datetime | None, row["started_at"]),
                cancel_requested_at=cast(datetime | None, row["cancel_requested_at"]),
                finished_at=cast(datetime | None, row["finished_at"]),
                research_result_fingerprint=cast(str | None, row["research_result_fingerprint"]),
                artifact_content_fingerprint=cast(str | None, row["artifact_content_fingerprint"]),
                failure=failure,
                calculation_execution_evidence_fingerprints=evidence,
                authoring_provenance=_decode_authoring_provenance(row.get("authoring_provenance")),
                strategy_research_composition_fingerprint=cast(
                    str | None, row.get("strategy_research_composition_fingerprint")
                ),
            )
        except (KeyError, TypeError, ValueError, OnlyResearchRunIntegrityError) as exc:
            raise OnlyResearchRunIntegrityError("PostgreSQL Research Run row failed strict verification") from exc


__all__ = ["OnlyPostgresResearchRunStore"]


def _decode_authoring_provenance(value: object) -> OnlyResearchAuthoringProvenance | None:
    if value is None:
        return None
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, Mapping):
        raise ValueError("Research authoring provenance must be a JSON object or null")
    provenance = OnlyResearchAuthoringProvenance.from_dict(payload)
    if only_canonical_json(payload) != only_canonical_json(provenance.to_dict()):
        raise ValueError("Research authoring provenance is not canonical")
    return provenance
