from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.market_data.durable import (
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyRevisionCommitService,
    only_build_coverage,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database import _backup, _restore_test
from tests.market_data_durable.conftest import BASE
from tests.market_data_durable.test_recovery_revision_dataset import _scope, _sealed
from tests.research.postgres.migration_support import copy_migrations_through

pytestmark = [
    pytest.mark.integration,
    pytest.mark.external,
    pytest.mark.requires_network,
    pytest.mark.postgres,
]


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
        admitted_at=fixed_now(),
        integration_binding_fingerprint="5" * 64,
    )
    assert catalog.admit_acquisition_intent(acquisition).admitted_at == fixed_now()
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


def _acquisition(source_id: str, binding: str) -> OnlyMarketDataAcquisitionIntent:
    return OnlyMarketDataAcquisitionIntent.build(
        source_id,
        _scope("TRADE"),
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        admitted_at=BASE,
        integration_binding_fingerprint=binding,
    )


def test_pre_0038_acquisition_identity_remains_exactly_readable(postgres_dsn: str, tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy-migrations"
    legacy_root.mkdir()
    copy_migrations_through(legacy_root, "0037_market_data_acquisition_attempt")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=legacy_root).migrate()
    scope = _scope("TRADE")
    fingerprint = only_canonical_fingerprint(
        {
            "source_id": "BINANCE_SPOT_LEGACY",
            "requested_scope": scope,
            "provenance": OnlyMarketDataProvenance.REST_BACKFILL.value,
        }
    )
    acquisition_id = f"acquisition:{fingerprint}"
    admitted_at = BASE.replace(hour=2)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO market_acquisition_intent "
            "(acquisition_id,request_fingerprint,source_id,requested_scope,provenance,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                acquisition_id,
                fingerprint,
                "BINANCE_SPOT_LEGACY",
                psycopg.types.json.Jsonb(only_canonical_payload(scope)),
                OnlyMarketDataProvenance.REST_BACKFILL.value,
                admitted_at,
            ),
        )

    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ("0038_market_data_acquisition_identity",)
    loaded = OnlyPostgresMarketDataCatalog(postgres_dsn).load_acquisition_intent(acquisition_id)

    assert loaded is not None
    assert loaded.acquisition_id == acquisition_id
    assert loaded.request_fingerprint == fingerprint
    assert loaded.admitted_at == admitted_at
    assert loaded.identity_version == 1
    assert loaded.integration_binding_fingerprint is None


def test_attempt_start_is_atomic_per_intent_and_keeps_interrupted_occurrences(
    postgres_dsn: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn)
    first = catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT", "1" * 64))
    second = catalog.admit_acquisition_intent(_acquisition("BINANCE_SPOT_TESTNET", "2" * 64))
    barrier = Barrier(10)

    def start_same(_: int) -> int:
        barrier.wait()
        return catalog.start_acquisition_attempt(first.acquisition_id, started_at=BASE).attempt_number

    with ThreadPoolExecutor(max_workers=10) as executor:
        numbers = tuple(executor.map(start_same, range(10)))

    assert set(numbers) == set(range(1, 11))
    latest = catalog.latest_acquisition_attempt(first.acquisition_id)
    assert latest is not None
    assert latest.attempt_number == 10
    assert latest.outcome is None and latest.completed_at is None

    distinct_barrier = Barrier(2)

    def start_distinct(acquisition_id: str) -> int:
        distinct_barrier.wait()
        return catalog.start_acquisition_attempt(acquisition_id, started_at=BASE).attempt_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        distinct = tuple(executor.map(start_distinct, (first.acquisition_id, second.acquisition_id)))
    assert distinct == (11, 1)
