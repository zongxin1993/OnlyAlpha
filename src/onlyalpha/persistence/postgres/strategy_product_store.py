"""PostgreSQL retry/admission adapter for Strategy Product commands."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeAdmissionState,
    OnlyStrategyFreezeCommandAdmission,
)
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId
from onlyalpha.research.run import OnlyResearchRunId
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from onlyalpha.strategy.errors import OnlyStrategyFreezeError, OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import OnlyStrategyFreezeOutcome, OnlyStrategyFreezeRequest
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionStage,
    only_verified_strategy_promotion_chain,
)

from .config import OnlyPostgresOperationalConnectionOptions
from .strategy_store import OnlyPostgresStrategyStore


class OnlyPostgresStrategyProductStore(OnlyPostgresStrategyStore):
    def __init__(
        self,
        dsn: str,
        semantic_namespace_id: OnlyResearchSemanticStoreId,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
    ) -> None:
        super().__init__(dsn, semantic_namespace_id, options)
        self._product_dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s",
                    (command_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Strategy Product receipt load failed") from exc
        return None if row is None else _receipt(cast(Mapping[str, object], row))

    def prepare_freeze_admission(
        self,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        request: OnlyStrategyFreezeRequest,
        prepared_at: datetime,
    ) -> OnlyStrategyFreezeCommandAdmission:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                receipt = connection.execute(
                    "SELECT command_id FROM product_command_receipt WHERE command_id = %s FOR UPDATE",
                    (command_id.value,),
                ).fetchone()
                if receipt is not None:
                    raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", command_id.value)
                row = connection.execute(
                    "SELECT * FROM strategy_freeze_command_admission WHERE command_id = %s FOR UPDATE",
                    (command_id.value,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """INSERT INTO strategy_freeze_command_admission
                        (command_id, command_fingerprint, research_run_id, candidate_fingerprint, actor, comment,
                         state, prepared_at, schema_version)
                        VALUES (%s, %s, %s, %s, %s, %s, 'PREPARED', %s, 1)""",
                        (
                            command_id.value,
                            command_fingerprint,
                            request.research_run_id.value,
                            request.candidate_fingerprint,
                            request.actor,
                            request.comment,
                            prepared_at,
                        ),
                    )
                    return OnlyStrategyFreezeCommandAdmission(
                        command_id,
                        command_fingerprint,
                        request,
                        OnlyStrategyFreezeAdmissionState.PREPARED,
                        prepared_at,
                    )
                return _freeze_admission(cast(Mapping[str, object], row))
        except OnlyStrategyFreezeError:
            raise
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_UNAVAILABLE", command_id.value) from exc

    def load_freeze_admission(self, command_id: OnlyProductCommandId) -> OnlyStrategyFreezeCommandAdmission:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM strategy_freeze_command_admission WHERE command_id = %s",
                    (command_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_UNAVAILABLE", command_id.value) from exc
        if row is None:
            raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_CORRUPT", command_id.value)
        return _freeze_admission(cast(Mapping[str, object], row))

    def complete_freeze_admission(
        self,
        admission: OnlyStrategyFreezeCommandAdmission,
        outcome: OnlyStrategyFreezeOutcome,
        completed_at: datetime,
    ) -> OnlyProductCommandReceipt:
        relation = outcome.freeze_record.record_fingerprint
        receipt = OnlyProductCommandReceipt(
            command_id=admission.command_id,
            command_kind=OnlyProductCommandKind.FREEZE_STRATEGY,
            command_fingerprint=admission.command_fingerprint,
            outcome_ref=OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.STRATEGY,
                outcome.strategy_fingerprint,
            ),
            accepted_at=completed_at,
        )
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM strategy_freeze_command_admission WHERE command_id = %s FOR UPDATE",
                    (admission.command_id.value,),
                ).fetchone()
                if row is None:
                    raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_CORRUPT", admission.command_id.value)
                current = _freeze_admission(cast(Mapping[str, object], row))
                if current.command_fingerprint != admission.command_fingerprint or current.request != admission.request:
                    raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", admission.command_id.value)
                existing_row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s FOR UPDATE",
                    (admission.command_id.value,),
                ).fetchone()
                if existing_row is not None:
                    return _receipt(cast(Mapping[str, object], existing_row))
                if current.state is OnlyStrategyFreezeAdmissionState.COMPLETED:
                    raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", admission.command_id.value)
                projection = connection.execute(
                    "SELECT freeze_record_fingerprint FROM strategy_freeze_record "
                    "WHERE freeze_record_fingerprint = %s AND strategy_fingerprint = %s",
                    (relation, outcome.strategy_fingerprint),
                ).fetchone()
                if projection is None:
                    raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_UNAVAILABLE", outcome.strategy_fingerprint)
                connection.execute(
                    """UPDATE strategy_freeze_command_admission
                    SET state = 'COMPLETED', strategy_fingerprint = %s, freeze_relation_fingerprint = %s,
                        published_at = %s, completed_at = %s
                    WHERE command_id = %s AND state = 'PREPARED'""",
                    (
                        outcome.strategy_fingerprint,
                        relation,
                        completed_at,
                        completed_at,
                        admission.command_id.value,
                    ),
                )
                _insert_receipt(connection, receipt)
            return receipt
        except OnlyStrategyFreezeError:
            raise
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_UNAVAILABLE", admission.command_id.value) from exc

    def append_promotion_with_receipt(
        self,
        record: OnlyStrategyPromotionRecord,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
    ) -> OnlyProductCommandReceipt:
        prepared = OnlyProductCommandReceipt(
            command_id=command_id,
            command_kind=OnlyProductCommandKind.PROMOTE_STRATEGY,
            command_fingerprint=command_fingerprint,
            outcome_ref=OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.STRATEGY_PROMOTION,
                record.record_fingerprint,
            ),
            accepted_at=record.recorded_at,
        )
        self.assert_namespace()
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                existing_row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s FOR UPDATE",
                    (command_id.value,),
                ).fetchone()
                if existing_row is not None:
                    return _receipt(cast(Mapping[str, object], existing_row))
                catalog = connection.execute(
                    "SELECT strategy_fingerprint FROM strategy_catalog WHERE strategy_fingerprint = %s FOR UPDATE",
                    (record.strategy_fingerprint,),
                ).fetchone()
                if catalog is None:
                    raise OnlyStrategyPromotionError("STRATEGY_NOT_FOUND", record.strategy_fingerprint)
                rows = connection.execute(
                    "SELECT * FROM strategy_promotion_record WHERE strategy_fingerprint = %s "
                    "ORDER BY promotion_record_fingerprint",
                    (record.strategy_fingerprint,),
                ).fetchall()
                chain = only_verified_strategy_promotion_chain(
                    tuple(_promotion(cast(Mapping[str, object], row)) for row in rows),
                    record.strategy_fingerprint,
                )
                expected = None if not chain else chain[-1].record_fingerprint
                if expected != record.previous_record_fingerprint:
                    raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CONFLICT", record.strategy_fingerprint)
                connection.execute(
                    """INSERT INTO strategy_promotion_record
                    (promotion_record_fingerprint, strategy_fingerprint, from_stage, to_stage,
                     evidence_fingerprints, previous_record_fingerprint, decision, reason, actor,
                     recorded_at, schema_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.record_fingerprint,
                        record.strategy_fingerprint,
                        record.from_stage.value,
                        record.to_stage.value,
                        list(record.evidence_fingerprints),
                        record.previous_record_fingerprint,
                        record.decision.value,
                        record.reason,
                        record.actor,
                        record.recorded_at,
                        record.schema_version,
                    ),
                )
                _insert_receipt(connection, prepared)
            return prepared
        except OnlyStrategyPromotionError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(command_id)
            if existing is not None:
                return existing
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CONFLICT", record.strategy_fingerprint) from exc
        except psycopg.Error as exc:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_UNAVAILABLE", record.strategy_fingerprint) from exc

    def load_promotion(self, record_fingerprint: str) -> OnlyStrategyPromotionRecord:
        try:
            with psycopg.connect(self._product_dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM strategy_promotion_record WHERE promotion_record_fingerprint = %s",
                    (record_fingerprint,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_UNAVAILABLE", record_fingerprint) from exc
        if row is None:
            raise OnlyStrategyPromotionError("PRODUCT_COMMAND_RECEIPT_CORRUPT", record_fingerprint)
        return _promotion(cast(Mapping[str, object], row))


def _freeze_admission(row: Mapping[str, object]) -> OnlyStrategyFreezeCommandAdmission:
    try:
        raw_state = str(row["state"])
        if raw_state == "PUBLISHED":
            raise ValueError("PUBLISHED Freeze admission is unsupported without receipt")
        state = OnlyStrategyFreezeAdmissionState(raw_state)
        return OnlyStrategyFreezeCommandAdmission(
            command_id=OnlyProductCommandId(str(row["command_id"])),
            command_fingerprint=str(row["command_fingerprint"]),
            request=OnlyStrategyFreezeRequest(
                research_run_id=OnlyResearchRunId(str(row["research_run_id"])),
                candidate_fingerprint=str(row["candidate_fingerprint"]),
                actor=str(row["actor"]),
                comment=None if row["comment"] is None else str(row["comment"]),
            ),
            state=state,
            prepared_at=cast(datetime, row["prepared_at"]),
            strategy_fingerprint=None if row["strategy_fingerprint"] is None else str(row["strategy_fingerprint"]),
            freeze_relation_fingerprint=(
                None if row["freeze_relation_fingerprint"] is None else str(row["freeze_relation_fingerprint"])
            ),
            completed_at=cast(datetime | None, row["completed_at"]),
        )
    except Exception as exc:
        if isinstance(exc, OnlyStrategyFreezeError):
            raise
        raise OnlyStrategyFreezeError("STRATEGY_FREEZE_ADMISSION_CORRUPT", str(row.get("command_id"))) from exc


def _receipt(row: Mapping[str, object]) -> OnlyProductCommandReceipt:
    try:
        return OnlyProductCommandReceipt(
            OnlyProductCommandId(str(row["command_id"])),
            OnlyProductCommandKind(str(row["command_kind"])),
            str(row["command_fingerprint"]),
            OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind(str(row["outcome_kind"])),
                str(row["outcome_id"]),
            ),
            cast(datetime, row["accepted_at"]),
            int(str(row["schema_version"])),
        )
    except Exception as exc:
        raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", str(row.get("command_id"))) from exc


def _promotion(row: Mapping[str, object]) -> OnlyStrategyPromotionRecord:
    try:
        evidence = row["evidence_fingerprints"]
        if not isinstance(evidence, list):
            raise ValueError("Promotion evidence is unavailable")
        result = OnlyStrategyPromotionRecord(
            strategy_fingerprint=str(row["strategy_fingerprint"]),
            from_stage=OnlyStrategyPromotionStage(str(row["from_stage"])),
            to_stage=OnlyStrategyPromotionStage(str(row["to_stage"])),
            evidence_fingerprints=tuple(str(item) for item in evidence),
            decision=OnlyStrategyPromotionDecision(str(row["decision"])),
            reason=str(row["reason"]),
            actor=str(row["actor"]),
            recorded_at=cast(datetime, row["recorded_at"]),
            previous_record_fingerprint=(
                None if row["previous_record_fingerprint"] is None else str(row["previous_record_fingerprint"])
            ),
            schema_version=int(str(row["schema_version"])),
        )
        if result.record_fingerprint != row["promotion_record_fingerprint"]:
            raise ValueError("Promotion fingerprint differs")
        return result
    except Exception as exc:
        raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", str(row.get("strategy_fingerprint"))) from exc


def _insert_receipt(connection, receipt: OnlyProductCommandReceipt) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        """INSERT INTO product_command_receipt
        (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            receipt.command_id.value,
            receipt.command_kind.value,
            receipt.command_fingerprint,
            receipt.outcome_ref.kind.value,
            receipt.outcome_ref.outcome_id,
            receipt.accepted_at,
            receipt.schema_version,
        ),
    )


__all__ = ["OnlyPostgresStrategyProductStore"]
