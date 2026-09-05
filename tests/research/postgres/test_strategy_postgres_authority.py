from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.qualification_product import (
    OnlyQualificationAdmissionState,
    OnlyQualificationCommandAdmission,
)
from onlyalpha.persistence.postgres import (
    OnlyPostgresResearchDeploymentStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.persistence.postgres.strategy_store import OnlyPostgresStrategyStore
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
)
from onlyalpha.strategy.errors import OnlyQualificationError, OnlyStrategyFreezeError, OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRecord
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionStage,
    _only_authorize_qualified_promotion,
)
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterionOutcome,
    OnlyQualificationCriterionResult,
    OnlyQualificationDecision,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
)
from tests.research.postgres.migration_support import copy_migrations_through

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 24, tzinfo=UTC)
NAMESPACE = OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000801")


def _store(postgres_dsn: str) -> OnlyPostgresStrategyStore:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(NAMESPACE)
    return OnlyPostgresStrategyStore(postgres_dsn, NAMESPACE)


def _product_store(postgres_dsn: str) -> OnlyPostgresStrategyProductStore:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(NAMESPACE)
    return OnlyPostgresStrategyProductStore(postgres_dsn, NAMESPACE)


def test_strategy_catalog_and_freeze_provenance_are_idempotent_without_semantic_json(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    record = OnlyStrategyFreezeRecord(
        "b" * 64,
        "c" * 64,
        ("f" * 64,),
        "a" * 64,
        "d" * 64,
        ("e" * 64,),
        "operator",
        NOW,
    )

    assert store.append_freeze_record(record) == record
    assert store.append_freeze_record(record) == record
    assert store.find_freeze_relation("b" * 64, "c" * 64, "a" * 64) == record

    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM strategy_catalog").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM strategy_freeze_record").fetchone() == (1,)
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'strategy_catalog'"
            ).fetchall()
        }
        assert not {"strategy_json", "decision_graph", "universe_json"} & columns


def test_strategy_projection_conflict_and_missing_relation_fail_closed(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)

    assert store.find_freeze_relation("b" * 64, "c" * 64, "a" * 64) is None
    with pytest.raises(OnlyStrategyFreezeError, match="STRATEGY_PROJECTION_CONFLICT"):
        store.ensure_strategy("a" * 64, 2)


def test_raw_strategy_promotion_append_is_retired_after_qualification_authority(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    first = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        ("b" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "backtest evidence",
        "operator",
        NOW,
    )
    with pytest.raises(OnlyStrategyPromotionError, match="QUALIFICATION_DECISION_NOT_APPROVED"):
        store.append(first)
    assert store.records("a" * 64) == ()


def test_promotion_command_concurrency_replays_same_intent_and_rejects_different_intent(
    postgres_dsn: str,
) -> None:
    store = _product_store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    command_id = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    record = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        ("b" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "backtest evidence",
        "operator",
        NOW,
        qualification_decision_fingerprint="b" * 64,
        schema_version=2,
    )
    barrier = Barrier(2)

    def append_same(_index: int):  # type: ignore[no-untyped-def]
        barrier.wait()
        return store.append_promotion_with_receipt(
            record,
            command_id,
            "c" * 64,
            _only_authorize_qualified_promotion("b" * 64),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(append_same, range(2)))

    assert receipts[0] == receipts[1]
    assert store.records(record.strategy_fingerprint) == (record,)

    conflicting = OnlyStrategyPromotionRecord(
        record.strategy_fingerprint,
        record.from_stage,
        record.to_stage,
        tuple(sorted(("b" * 64, "d" * 64))),
        record.decision,
        "different intent",
        record.actor,
        record.recorded_at,
        qualification_decision_fingerprint="b" * 64,
        schema_version=2,
    )
    with pytest.raises(OnlyStrategyPromotionError, match="PRODUCT_COMMAND_CONFLICT"):
        store.append_promotion_with_receipt(
            conflicting,
            command_id,
            "e" * 64,
            _only_authorize_qualified_promotion("b" * 64),
        )


def test_qualification_command_admission_and_schema_v2_promotion_survive_restart(postgres_dsn: str) -> None:
    store = _product_store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
        "b" * 64,
    )
    decision = OnlyQualificationDecision(
        "a" * 64,
        OnlyQualificationGate.BACKTEST_TO_SIM,
        "backtest-gate",
        "1",
        "c" * 64,
        (evidence,),
        (
            OnlyQualificationCriterionResult(
                "has-result",
                evidence.evidence_fingerprint,
                "backtest.artifact_count",
                Decimal(1),
                "GE",
                Decimal(1),
                OnlyQualificationCriterionOutcome.PASS,
            ),
        ),
        OnlyQualificationOutcome.APPROVED,
    )
    command_id = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab")
    admission = OnlyQualificationCommandAdmission(
        command_id,
        "d" * 64,
        decision.subject_strategy_fingerprint,
        decision.policy_id,
        decision.policy_version,
        decision.evidence,
        OnlyQualificationAdmissionState.PREPARED,
        NOW,
    )
    assert store.prepare_qualification_admission(admission) == admission
    receipt = store.complete_qualification_admission(admission, decision, NOW)
    assert receipt.outcome_ref.outcome_id == decision.decision_fingerprint
    restarted = OnlyPostgresStrategyProductStore(postgres_dsn, NAMESPACE)
    loaded = restarted.load_qualification_admission(command_id)
    assert loaded.state is OnlyQualificationAdmissionState.COMPLETED
    assert loaded.decision_fingerprint == decision.decision_fingerprint
    with pytest.raises(OnlyQualificationError, match="PRODUCT_COMMAND_CONFLICT"):
        restarted.prepare_qualification_admission(
            OnlyQualificationCommandAdmission(
                command_id,
                "e" * 64,
                admission.subject_strategy_fingerprint,
                admission.policy_id,
                admission.policy_version,
                admission.evidence,
                OnlyQualificationAdmissionState.PREPARED,
                NOW,
            )
        )

    promotion = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        tuple(sorted(("f" * 64, decision.decision_fingerprint))),
        OnlyStrategyPromotionDecision.APPROVED,
        "qualification-backed",
        "operator",
        NOW,
        qualification_decision_fingerprint=decision.decision_fingerprint,
        schema_version=2,
    )
    store.append_promotion_with_receipt(
        promotion,
        OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaac"),
        "1" * 64,
        _only_authorize_qualified_promotion(decision.decision_fingerprint),
    )
    assert restarted.load_promotion(promotion.record_fingerprint) == promotion


def test_qualification_command_concurrency_has_one_exact_decision_binding(postgres_dsn: str) -> None:
    store = _product_store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
        "b" * 64,
    )
    decision = OnlyQualificationDecision(
        "a" * 64,
        OnlyQualificationGate.BACKTEST_TO_SIM,
        "backtest-gate",
        "1",
        "c" * 64,
        (evidence,),
        (
            OnlyQualificationCriterionResult(
                "has-result",
                evidence.evidence_fingerprint,
                "backtest.artifact_count",
                Decimal(1),
                "GE",
                Decimal(1),
                OnlyQualificationCriterionOutcome.PASS,
            ),
        ),
        OnlyQualificationOutcome.APPROVED,
    )
    command_id = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaad")
    admission = OnlyQualificationCommandAdmission(
        command_id,
        "d" * 64,
        decision.subject_strategy_fingerprint,
        decision.policy_id,
        decision.policy_version,
        decision.evidence,
        OnlyQualificationAdmissionState.PREPARED,
        NOW,
    )
    barrier = Barrier(2)

    def evaluate_same(_index: int):  # type: ignore[no-untyped-def]
        candidate_store = OnlyPostgresStrategyProductStore(postgres_dsn, NAMESPACE)
        barrier.wait()
        prepared = candidate_store.prepare_qualification_admission(admission)
        return candidate_store.complete_qualification_admission(prepared, decision, NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(evaluate_same, range(2)))

    assert receipts[0] == receipts[1]
    assert receipts[0].outcome_ref.outcome_id == decision.decision_fingerprint
    assert store.load_qualification_admission(command_id).decision_fingerprint == decision.decision_fingerprint


def test_m20_preserves_legacy_promotion_without_fabricating_qualification(postgres_dsn: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    legacy_migrations = tmp_path / "legacy-migrations"
    legacy_migrations.mkdir()
    copy_migrations_through(legacy_migrations, "0019_research_authoring_provenance")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=legacy_migrations).migrate()
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(NAMESPACE)
    legacy = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        ("b" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "pre-B2.5 historical fact",
        "operator",
        NOW,
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO strategy_catalog "
            "(strategy_fingerprint, semantic_namespace_id, schema_version) VALUES (%s, %s, 1)",
            (legacy.strategy_fingerprint, NAMESPACE.value),
        )
        connection.execute(
            """INSERT INTO strategy_promotion_record
            (promotion_record_fingerprint, strategy_fingerprint, from_stage, to_stage,
             evidence_fingerprints, previous_record_fingerprint, decision, reason, actor,
             recorded_at, schema_version)
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, 1)""",
            (
                legacy.record_fingerprint,
                legacy.strategy_fingerprint,
                legacy.from_stage.value,
                legacy.to_stage.value,
                list(legacy.evidence_fingerprints),
                legacy.decision.value,
                legacy.reason,
                legacy.actor,
                legacy.recorded_at,
            ),
        )

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    persisted = OnlyPostgresStrategyProductStore(postgres_dsn, NAMESPACE).load_promotion(legacy.record_fingerprint)
    assert persisted == legacy
    assert persisted.schema_version == 1
    assert persisted.qualification_decision_fingerprint is None


def test_strategy_store_fails_closed_on_semantic_namespace_mismatch(postgres_dsn: str) -> None:
    _store(postgres_dsn)
    mismatched = OnlyPostgresStrategyStore(
        postgres_dsn,
        OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000802"),
    )

    with pytest.raises(OnlyResearchDeploymentError) as error:
        mismatched.ensure_strategy("a" * 64, 1)
    assert error.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH


def test_strategy_store_fails_closed_when_semantic_namespace_is_unbound(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    store = OnlyPostgresStrategyStore(postgres_dsn, NAMESPACE)

    with pytest.raises(OnlyResearchDeploymentError) as error:
        store.ensure_strategy("a" * 64, 1)
    assert error.value.code is OnlyResearchDeploymentErrorCode.DEPLOYMENT_BINDING_MISSING
