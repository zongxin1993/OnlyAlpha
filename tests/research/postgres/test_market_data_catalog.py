from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.market_data.durable import (
    OnlyInMemoryMarketFactStore,
    OnlyRevisionCommitService,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database import _backup, _restore_test
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
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
