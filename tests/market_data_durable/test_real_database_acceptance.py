from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataBackfillCoordinator,
    OnlyMarketDataIngress,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)
from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseMarketFactStore,
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.postgres import OnlyPostgresMarketDataCatalog, only_assert_postgres_test_database
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database import _backup, _restore_test
from scripts.market_data_database import _backup_segment, _restore_segment

from .conftest import BAR_TYPE, BASE, INSTRUMENT, SOURCE, VERSION
from .test_backfill_and_correction import _HistoricalSource, _two_minute_scope, _write_bar

pytestmark = [
    pytest.mark.p9_3_real_database,
    pytest.mark.postgres,
    pytest.mark.clickhouse,
    pytest.mark.external,
    pytest.mark.requires_network,
]


def _clickhouse(database: str) -> OnlyClickHouseClient:
    url = os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_URL")
    if not url:
        pytest.fail("ONLYALPHA_TEST_CLICKHOUSE_URL is required")
    return OnlyClickHouseClient(
        OnlyClickHouseConfig(
            url,
            database=database,
            user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
            password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
            storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
        )
    )


def test_combined_real_database_authority_recovery_and_maintenance(tmp_path: Path) -> None:
    postgres_dsn = os.environ.get("ONLYALPHA_TEST_POSTGRES_DSN")
    if not postgres_dsn:
        pytest.fail("ONLYALPHA_TEST_POSTGRES_DSN is required")
    only_assert_postgres_test_database(postgres_dsn)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()

    database = os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_DATABASE", f"onlyalpha_test_{uuid.uuid4().hex}")
    only_assert_clickhouse_test_database(database)
    client = _clickhouse(database)
    OnlyClickHouseMigrationAuthority(client).migrate()
    fixed_now = lambda: BASE + timedelta(hours=1)  # noqa: E731 - explicit deterministic clock input
    wal = OnlyMarketDataWal(tmp_path / "wal", capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    initial_id = _write_bar(ingress, "accept-initial", 0, "101.00000000")
    store = OnlyClickHouseMarketFactStore(client)
    catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=fixed_now)
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _two_minute_scope()
    assert recovery.drain(initial_id, scope) == "DURABLE_ONLY:INCOMPLETE"
    assert wal.scan_uncommitted() == ()

    source = _HistoricalSource(ingress)
    backfill = OnlyMarketDataBackfillCoordinator(source, catalog, store, recovery, committer)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        str(SOURCE), scope, provenance=OnlyMarketDataProvenance.REST_BACKFILL, created_at=fixed_now()
    )
    [gap] = backfill.inspect(acquisition).gaps
    request = OnlyHistoricalBarRequest(
        "real-gap",
        frozenset({INSTRUMENT}),
        frozenset({BAR_TYPE}),
        OnlyHistoricalDataRange(BASE + timedelta(minutes=1), BASE + timedelta(minutes=2)),
        VERSION,
    )
    result = backfill.backfill_bar_gap(acquisition, request, gap)  # type: ignore[arg-type]
    assert result.revision is not None and result.seal is not None and result.manifest.complete

    fresh_client = _clickhouse(database)
    fresh_store = OnlyClickHouseMarketFactStore(fresh_client)
    fresh_catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=fixed_now)
    fresh_wal = OnlyMarketDataWal(tmp_path / "wal", capacity_bytes=2_000_000, now=fixed_now)
    fresh_recovery = OnlyMarketDataRecoveryCoordinator(
        fresh_wal,
        fresh_store,
        fresh_catalog,
        OnlyRevisionCommitService(fresh_store, fresh_catalog, now=fixed_now),
    )
    assert fresh_recovery.recover_all() == ()
    assert (
        len(
            OnlyHistoricalMarketDataQueryService(fresh_catalog, fresh_store).read_exact(
                result.revision.revision_id, scope
            )
        )
        == 2
    )

    before = fresh_client.query_json("SELECT count() count, groupBitXor(cityHash64(tuple(*))) hash FROM market_bar")
    fresh_client.execute("ALTER TABLE market_bar MOVE PARTITION 202601 TO VOLUME 'cold'")
    after = fresh_client.query_json("SELECT count() count, groupBitXor(cityHash64(tuple(*))) hash FROM market_bar")
    assert after == before

    backup = tmp_path / "postgres.dump"
    restore_dsn = postgres_dsn.rsplit("/", 1)[0] + "/onlyalpha_restore_test"
    admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        connection.execute("CREATE DATABASE onlyalpha_restore_test")
    restore_database = f"onlyalpha_restore_{uuid.uuid4().hex}"
    restored_clickhouse = _clickhouse(restore_database)
    try:
        _backup(postgres_dsn, backup)
        _restore_test(postgres_dsn, restore_dsn, backup, None)
        assert (
            OnlyPostgresMarketDataCatalog(restore_dsn).load_sealed_revision(result.revision.revision_id)[0]
            == result.revision
        )

        OnlyClickHouseMigrationAuthority(restored_clickhouse).migrate()
        segment_backup = tmp_path / "segment.json"
        _backup_segment(fresh_client, result.revision.segment_refs[-1][0], segment_backup)
        _restore_segment(restored_clickhouse, segment_backup)
        assert int(str(restored_clickhouse.query_json("SELECT count() count FROM market_bar")[0]["count"])) == 1
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onlyalpha_restore_test'"
            )
            connection.execute("DROP DATABASE IF EXISTS onlyalpha_restore_test")
        restored_clickhouse.execute(f"DROP DATABASE IF EXISTS {restore_database} SYNC", database="default")
        client.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")
