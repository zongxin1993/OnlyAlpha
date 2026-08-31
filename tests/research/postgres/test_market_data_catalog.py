from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.market_data.durable import (
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyRevisionCommitService,
    only_build_coverage,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database import _backup, _major_upgrade_test, _restore_test
from tests.market_data_durable.conftest import BASE
from tests.market_data_durable.test_recovery_revision_dataset import _scope, _sealed

pytestmark = pytest.mark.postgres


def test_market_data_catalog_concurrent_commit_is_immutable_and_survives_restore(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()

    def fixed_now():  # type: ignore[no-untyped-def]
        return BASE.replace(hour=1)

    wal, segment, _ = _sealed(tmp_path / "wal", fixed_now)
    records = wal.read_sealed(segment.segment_id)
    fact_store = OnlyInMemoryMarketFactStore()
    fact_store.write_segment(segment, records)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    manifest, revision, seal = OnlyRevisionCommitService(fact_store, catalog, now=fixed_now).commit(
        segment, _scope("TRADE"), {segment.segment_id: records}
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _: catalog.commit_revision((segment,), manifest, revision, seal),
                range(2),
            )
        )
    assert results == (None, None)
    assert catalog.load_sealed_revision(revision.revision_id) == (revision, seal)
    assert catalog.load_durable_segments((segment.segment_id,)) == (segment,)
    assert catalog.list_durable_segments(_scope("TRADE")) == (segment,)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        "BINANCE_SPOT",
        _scope("TRADE"),
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        created_at=fixed_now(),
    )
    catalog.commit_acquisition_intent(acquisition)
    incomplete_scope = replace(_scope("TRADE"), first_sequence=10, last_sequence=11)
    incomplete = only_build_coverage(
        incomplete_scope,
        (segment,),
        tuple(fact for bundle in records for fact in bundle.canonical_facts),
    )
    catalog.commit_coverage_manifest(incomplete)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT state FROM market_segment_state_event WHERE segment_id=%s ORDER BY state",
            (segment.segment_id,),
        ).fetchall() == [("DURABLE_SEGMENT_COMMITTED",)]
        assert connection.execute(
            "SELECT provenance FROM market_acquisition_intent WHERE acquisition_id=%s",
            (acquisition.acquisition_id,),
        ).fetchone() == ("REST_BACKFILL",)
        assert connection.execute(
            "SELECT coverage_status,gaps FROM market_coverage_manifest WHERE manifest_id=%s",
            (incomplete.manifest_id,),
        ).fetchone() == ("INCOMPLETE", [{"first_sequence": 11, "last_sequence": 11}])

    conflicting_seal = replace(
        seal,
        seal_id=f"{seal.seal_id}:conflict",
        checks=seal.checks + ("UNDECLARED_CHECK",),
        sealed_at=seal.sealed_at + timedelta(microseconds=1),
    )
    with pytest.raises(RuntimeError, match="POSTGRES_MARKET_DATA_COMMIT_CONFLICT"):
        catalog.commit_revision((segment,), manifest, revision, conflicting_seal)
    assert catalog.load_sealed_revision(revision.revision_id) == (revision, seal)

    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.RaiseException):
        connection.execute(
            "UPDATE market_data_revision SET creation_reason='MUTATED' WHERE revision_id=%s",
            (revision.revision_id,),
        )

    backup = tmp_path / "market-data.dump"
    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    try:
        _backup(postgres_dsn, backup)
        _restore_test(postgres_dsn, target_dsn, backup, None)
        restored = OnlyPostgresMarketDataCatalog(target_dsn)
        assert restored.load_sealed_revision(revision.revision_id) == (revision, seal)
        assert restored.load_durable_segments((segment.segment_id,)) == (segment,)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")


def test_postgres_16_catalog_logical_upgrade_to_18_preserves_exact_durable_truth(
    postgres_dsn: str, tmp_path: Path
) -> None:
    source_dsn = os.environ.get("ONLYALPHA_TEST_POSTGRES16_DSN")
    if not source_dsn:
        pytest.fail("ONLYALPHA_TEST_POSTGRES16_DSN is required for the canonical PostgreSQL major-upgrade proof")
    with psycopg.connect(source_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(source_dsn).migrate()

    def fixed_now():  # type: ignore[no-untyped-def]
        return BASE.replace(hour=1)

    wal, segment, _ = _sealed(tmp_path / "upgrade-wal", fixed_now)
    records = wal.read_sealed(segment.segment_id)
    fact_store = OnlyInMemoryMarketFactStore()
    fact_store.write_segment(segment, records)
    source_catalog = OnlyPostgresMarketDataCatalog._legacy_upgrade_test_source(source_dsn)
    _, revision, seal = OnlyRevisionCommitService(fact_store, source_catalog, now=fixed_now).commit(
        segment, _scope("TRADE"), {segment.segment_id: records}
    )

    target_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_upgrade_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_upgrade_test")
        connection.execute("CREATE DATABASE onlyalpha_upgrade_test")
    try:
        _major_upgrade_test(source_dsn, target_dsn, tmp_path / "postgres-16-to-18.dump")
        upgraded = OnlyPostgresMarketDataCatalog(target_dsn)
        assert upgraded.load_durable_segments((segment.segment_id,)) == (segment,)
        assert upgraded.load_sealed_revision(revision.revision_id) == (revision, seal)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onlyalpha_upgrade_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_upgrade_test")
