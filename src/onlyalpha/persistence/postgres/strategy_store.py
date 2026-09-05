"""PostgreSQL catalog and append-only evidence adapters for Strategy products."""

from __future__ import annotations

from datetime import datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
)
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from onlyalpha.strategy.errors import OnlyStrategyFreezeError, OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRecord
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionStage,
    only_verified_strategy_promotion_chain,
)

from .config import OnlyPostgresOperationalConnectionOptions


class OnlyPostgresStrategyStore:
    """Stores catalog/provenance only; immutable Strategy JSON never enters PostgreSQL."""

    def __init__(
        self,
        dsn: str,
        semantic_namespace_id: OnlyResearchSemanticStoreId,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._namespace = semantic_namespace_id

    def assert_namespace(self) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                row = connection.execute(
                    "SELECT semantic_store_id FROM research_deployment_semantic_store_binding WHERE singleton = TRUE"
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Strategy semantic namespace binding unavailable") from exc
        if row is None:
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.DEPLOYMENT_BINDING_MISSING)
        if str(row[0]) != str(self._namespace):
            raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH)

    def ensure_strategy(self, strategy_fingerprint: str, schema_version: int) -> None:
        self.assert_namespace()
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(
                    "INSERT INTO strategy_catalog "
                    "(strategy_fingerprint, semantic_namespace_id, schema_version) VALUES (%s, %s, %s) "
                    "ON CONFLICT (strategy_fingerprint) DO NOTHING",
                    (strategy_fingerprint, str(self._namespace), schema_version),
                )
                row = connection.execute(
                    "SELECT semantic_namespace_id, schema_version FROM strategy_catalog WHERE strategy_fingerprint = %s",
                    (strategy_fingerprint,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_UNAVAILABLE", strategy_fingerprint) from exc
        if row is None or (str(row[0]), int(row[1])) != (self._namespace.value, schema_version):
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_CONFLICT", strategy_fingerprint)

    def find_freeze_relation(
        self,
        candidate_fingerprint: str,
        research_result_fingerprint: str,
        strategy_fingerprint: str,
    ) -> OnlyStrategyFreezeRecord | None:
        self.assert_namespace()
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM strategy_freeze_record WHERE candidate_fingerprint = %s "
                    "AND research_result_fingerprint = %s AND strategy_fingerprint = %s",
                    (candidate_fingerprint, research_result_fingerprint, strategy_fingerprint),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_UNAVAILABLE", strategy_fingerprint) from exc
        return None if row is None else _freeze_record(row)

    def append_freeze_record(self, record: OnlyStrategyFreezeRecord) -> OnlyStrategyFreezeRecord:
        self.assert_namespace()
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute(
                    "INSERT INTO strategy_freeze_record "
                    "(freeze_record_fingerprint, candidate_fingerprint, research_result_fingerprint, "
                    "research_execution_evidence_fingerprints, strategy_fingerprint, "
                    "admission_evidence_fingerprint, equivalence_evidence_fingerprints, "
                    "actor, created_at, comment, schema_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (candidate_fingerprint, research_result_fingerprint, strategy_fingerprint) DO NOTHING",
                    (
                        record.record_fingerprint,
                        record.candidate_fingerprint,
                        record.research_result_fingerprint,
                        list(record.research_execution_evidence_fingerprints),
                        record.strategy_fingerprint,
                        record.admission_evidence_fingerprint,
                        list(record.equivalence_evidence_fingerprints),
                        record.actor,
                        record.created_at,
                        record.comment,
                        record.schema_version,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM strategy_freeze_record WHERE candidate_fingerprint = %s "
                    "AND research_result_fingerprint = %s AND strategy_fingerprint = %s",
                    (record.candidate_fingerprint, record.research_result_fingerprint, record.strategy_fingerprint),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_UNAVAILABLE", record.strategy_fingerprint) from exc
        if row is None:
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_UNAVAILABLE", record.strategy_fingerprint)
        actual = _freeze_record(row)
        if actual.record_fingerprint != record.record_fingerprint:
            raise OnlyStrategyFreezeError("STRATEGY_PROJECTION_CONFLICT", record.strategy_fingerprint)
        return actual

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
        self.assert_namespace()
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT * FROM strategy_promotion_record WHERE strategy_fingerprint = %s "
                    "ORDER BY promotion_record_fingerprint",
                    (strategy_fingerprint,),
                ).fetchall()
        except psycopg.Error as exc:
            raise OnlyStrategyPromotionError("PROMOTION_LEDGER_UNAVAILABLE", strategy_fingerprint) from exc
        return only_verified_strategy_promotion_chain(
            tuple(_promotion_record(row) for row in rows),
            strategy_fingerprint,
        )

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
        raise OnlyStrategyPromotionError(
            "QUALIFICATION_DECISION_NOT_APPROVED",
            f"raw Promotion append is retired for {record.strategy_fingerprint}",
        )


def _freeze_record(row: dict[str, object]) -> OnlyStrategyFreezeRecord:
    try:
        evidence = row["equivalence_evidence_fingerprints"]
        provenance = row["research_execution_evidence_fingerprints"]
        if not isinstance(evidence, list) or not isinstance(provenance, list):
            raise ValueError("exact equivalence evidence is unavailable")
        record = OnlyStrategyFreezeRecord(
            candidate_fingerprint=str(row["candidate_fingerprint"]),
            research_result_fingerprint=str(row["research_result_fingerprint"]),
            research_execution_evidence_fingerprints=tuple(str(item) for item in provenance),
            strategy_fingerprint=str(row["strategy_fingerprint"]),
            admission_evidence_fingerprint=str(row["admission_evidence_fingerprint"]),
            equivalence_evidence_fingerprints=tuple(str(item) for item in evidence),
            actor=str(row["actor"]),
            created_at=cast(datetime, row["created_at"]),
            comment=None if row["comment"] is None else str(row["comment"]),
            schema_version=int(str(row["schema_version"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OnlyStrategyFreezeError("STRATEGY_CATALOG_CORRUPT", str(row.get("strategy_fingerprint", ""))) from exc
    if record.record_fingerprint != row["freeze_record_fingerprint"]:
        raise OnlyStrategyFreezeError("STRATEGY_CATALOG_CORRUPT", record.strategy_fingerprint)
    return record


def _promotion_record(row: dict[str, object]) -> OnlyStrategyPromotionRecord:
    record = OnlyStrategyPromotionRecord(
        str(row["strategy_fingerprint"]),
        OnlyStrategyPromotionStage(str(row["from_stage"])),
        OnlyStrategyPromotionStage(str(row["to_stage"])),
        tuple(str(item) for item in cast(list[object], row["evidence_fingerprints"])),
        OnlyStrategyPromotionDecision(str(row["decision"])),
        str(row["reason"]),
        str(row["actor"]),
        cast(datetime, row["recorded_at"]),
        None if row["previous_record_fingerprint"] is None else str(row["previous_record_fingerprint"]),
        None
        if row.get("qualification_decision_fingerprint") is None
        else str(row["qualification_decision_fingerprint"]),
        int(str(row["schema_version"])),
    )
    if record.record_fingerprint != row["promotion_record_fingerprint"]:
        raise OnlyStrategyPromotionError("PROMOTION_LEDGER_CORRUPT", record.strategy_fingerprint)
    return record


__all__ = ["OnlyPostgresStrategyStore"]
