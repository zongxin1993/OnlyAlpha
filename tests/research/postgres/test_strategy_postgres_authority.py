from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from onlyalpha.persistence.postgres import (
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresStrategyStore,
)
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
)
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRecord
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionStage,
)

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 24, tzinfo=UTC)
NAMESPACE = OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000801")


def _store(postgres_dsn: str) -> OnlyPostgresStrategyStore:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(NAMESPACE)
    return OnlyPostgresStrategyStore(postgres_dsn, NAMESPACE)


def test_strategy_catalog_and_freeze_provenance_are_idempotent_without_semantic_json(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    store.ensure_strategy("a" * 64, 1)
    record = OnlyStrategyFreezeRecord(
        "b" * 64,
        "c" * 64,
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


def test_strategy_promotion_is_exact_append_only_chain(postgres_dsn: str) -> None:
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
    second = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.BACKTEST,
        OnlyStrategyPromotionStage.SIM,
        ("c" * 64,),
        OnlyStrategyPromotionDecision.APPROVED,
        "sim evidence",
        "operator",
        NOW - timedelta(seconds=1),
        first.record_fingerprint,
    )

    store.append(first)
    store.append(second)
    assert store.records("a" * 64) == (first, second)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.ForeignKeyViolation):
        connection.execute(
            "DELETE FROM strategy_promotion_record WHERE promotion_record_fingerprint = %s", (first.record_fingerprint,)
        )


def test_strategy_store_fails_closed_on_semantic_namespace_mismatch(postgres_dsn: str) -> None:
    _store(postgres_dsn)
    mismatched = OnlyPostgresStrategyStore(
        postgres_dsn,
        OnlyResearchSemanticStoreId("00000000-0000-4000-8000-000000000802"),
    )

    with pytest.raises(OnlyResearchDeploymentError) as error:
        mismatched.ensure_strategy("a" * 64, 1)
    assert error.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH
