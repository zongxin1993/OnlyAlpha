from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import time, timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.market_data.aggregation.time_bar import OnlyTimeBarAggregator
from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataBackfillCoordinator,
    OnlyMarketDataIngress,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionIdentity,
    only_plan_bar_resolution,
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

from .conftest import BAR_CONSTRUCTION, BAR_TYPE, BASE, INSTRUMENT, SOURCE, VERSION, bar_update
from .test_backfill_and_correction import _HistoricalSource, _two_minute_scope, _write_bar
from .test_recovery_revision_dataset import _observation

pytestmark = [
    pytest.mark.database_acceptance,
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
    postgres_dsn = os.environ.get("ONLYALPHA_POSTGRES_DSN")
    if not postgres_dsn:
        pytest.fail("ONLYALPHA_POSTGRES_DSN is required")
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
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
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
        str(SOURCE),
        scope,
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        admitted_at=fixed_now(),
        integration_binding_fingerprint="4" * 64,
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
    if fresh_client.config.storage_policy == "default":
        storage = fresh_client.query_json(
            "SELECT storage_policy FROM system.tables WHERE database = currentDatabase() AND name = 'market_bar'"
        )
        assert storage == ({"storage_policy": "default"},)
    else:
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


def test_native_fifteen_minute_revision_survives_real_database_restart(tmp_path: Path) -> None:
    postgres_dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(postgres_dsn)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    database = f"onlyalpha_test_{uuid.uuid4().hex}"
    client = _clickhouse(database)
    OnlyClickHouseMigrationAuthority(client).migrate()
    try:
        specification = OnlyBarSemantic.fixed_duration(15)
        bar_type = OnlyBarType(INSTRUMENT, specification)
        plan = only_plan_bar_resolution(
            specification,
            (OnlyBarCapability(specification, True, True, "UTC", grid_origin_ns=0),),
            calendar_fingerprint="UTC",
            source_id=str(SOURCE),
            instrument_id=str(INSTRUMENT),
            integration_revision_fingerprint="a" * 64,
        )
        construction = OnlyBarConstructionIdentity.build(plan, data_version=str(VERSION))
        now = lambda: BASE + timedelta(hours=1)  # noqa: E731
        wal = OnlyMarketDataWal(tmp_path / "native-wal", capacity_bytes=2_000_000, now=now)
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id="binance-spot",
            normalizer_version="1",
            ingest_clock_ns=lambda: 5,
            bar_construction=construction,
        )
        ingress.begin_segment("native-fifteen")
        base = bar_update()
        end = BASE + timedelta(minutes=15)
        bar = replace(base.payload.bar, bar_type=bar_type, bar_end=end, ts_event=end, ts_init=end)
        update = replace(
            base,
            update_id=only_bar_update_id(SOURCE, INSTRUMENT, bar_type, BASE, VERSION),
            payload=OnlyBarUpdate(bar),
            ts_event=OnlyTimestamp.from_datetime(end),
            ts_init=OnlyTimestamp.from_datetime(end),
            sequence_scope=None,
        )
        ingress.record(_observation(15), update)
        segment = ingress.seal()
        scope = OnlyMarketDataScope(
            str(SOURCE),
            "SPOT",
            str(INSTRUMENT),
            "BAR",
            OnlyTimestamp.from_datetime(BASE).unix_nanos,
            OnlyTimestamp.from_datetime(end).unix_nanos,
            str(VERSION),
            only_canonical_fingerprint(bar_type.to_dict()),
            bar_construction=construction,
        )
        records = wal.read_sealed(segment.segment_id)
        store = OnlyClickHouseMarketFactStore(client)
        store.write_segment(segment, records)
        catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=now)
        _, revision, seal = OnlyRevisionCommitService(store, catalog, now=now).commit(
            segment,
            scope,
            {segment.segment_id: records},
        )
        fresh_store = OnlyClickHouseMarketFactStore(_clickhouse(database))
        fresh_catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=now)
        restored, restored_seal = fresh_catalog.load_sealed_revision(revision.revision_id)
        assert restored == revision and restored_seal == seal
        assert restored.scope.bar_construction == construction
        assert fresh_catalog.load_durable_segments((segment.segment_id,)) == (segment,)
        assert (
            len(
                OnlyHistoricalMarketDataQueryService(fresh_catalog, fresh_store).read_exact(revision.revision_id, scope)
            )
            == 1
        )
    finally:
        client.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")


def test_derived_seven_minute_identity_rebuilds_from_real_sealed_base(tmp_path: Path) -> None:
    postgres_dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(postgres_dsn)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    database = f"onlyalpha_test_{uuid.uuid4().hex}"
    client = _clickhouse(database)
    OnlyClickHouseMigrationAuthority(client).migrate()
    try:
        calendar = OnlyTradingCalendar(
            OnlyCalendarId("TEST-24X7"),
            OnlyVenueId("BINANCE"),
            OnlyTimeZone("UTC"),
            (OnlyTradingSession("continuous", time(0), time(0), OnlySessionType.CONTINUOUS),),
            weekend_days=(),
        )
        alignment = only_canonical_fingerprint(calendar.to_dict())
        capability = OnlyBarCapability(
            BAR_TYPE.semantic,
            True,
            True,
            alignment,
            grid_origin_ns=0,
        )

        def plan(specification: OnlyBarSemantic):  # type: ignore[no-untyped-def]
            return only_plan_bar_resolution(
                specification,
                (capability,),
                calendar_fingerprint=alignment,
                source_id=str(SOURCE),
                instrument_id=str(INSTRUMENT),
                integration_revision_fingerprint="a" * 64,
            )

        base_construction = OnlyBarConstructionIdentity.build(plan(BAR_TYPE.semantic), data_version=str(VERSION))
        now = lambda: BASE + timedelta(hours=1)  # noqa: E731
        wal = OnlyMarketDataWal(tmp_path / "derived-wal", capacity_bytes=2_000_000, now=now)
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id="binance-spot",
            normalizer_version="1",
            ingest_clock_ns=lambda: 5,
            bar_construction=base_construction,
        )
        ingress.begin_segment("derived-seven-base")
        for index in range(7):
            ingress.record(_observation(20 + index), bar_update(index))
        segment = ingress.seal()
        scope = OnlyMarketDataScope(
            str(SOURCE),
            "SPOT",
            str(INSTRUMENT),
            "BAR",
            OnlyTimestamp.from_datetime(BASE).unix_nanos,
            OnlyTimestamp.from_datetime(BASE + timedelta(minutes=7)).unix_nanos,
            str(VERSION),
            only_canonical_fingerprint(BAR_TYPE.to_dict()),
            bar_construction=base_construction,
        )
        records = wal.read_sealed(segment.segment_id)
        store = OnlyClickHouseMarketFactStore(client)
        store.write_segment(segment, records)
        catalog = OnlyPostgresMarketDataCatalog(postgres_dsn, now=now)
        _, revision, seal = OnlyRevisionCommitService(store, catalog, now=now).commit(
            segment,
            scope,
            {segment.segment_id: records},
        )
        target = OnlyBarSemantic.fixed_duration(7)
        derived_plan = plan(target)

        def reconstruct(
            current_catalog: OnlyPostgresMarketDataCatalog,
            current_store: OnlyClickHouseMarketFactStore,
        ) -> tuple[str, object]:
            exact_revision, exact_seal = current_catalog.load_sealed_revision(revision.revision_id)
            construction = OnlyBarConstructionIdentity.build(
                derived_plan,
                data_version=str(VERSION),
                base_revision_id=exact_revision.revision_id,
                base_revision_fingerprint=exact_revision.fingerprint,
                base_seal_id=exact_seal.seal_id,
            )
            source_bars = tuple(
                OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload).payload.bar
                for fact in OnlyHistoricalMarketDataQueryService(current_catalog, current_store).read_exact(
                    revision.revision_id,
                    scope,
                )
            )
            aggregator = OnlyTimeBarAggregator(
                BAR_TYPE,
                OnlyBarType(INSTRUMENT, target),
                calendar,
                OnlyBacktestClock(BASE + timedelta(hours=1)),
            )
            projected = tuple(bar for source in source_bars if (bar := aggregator.process(source)) is not None)
            return construction.fingerprint, projected

        before = reconstruct(catalog, store)
        after = reconstruct(
            OnlyPostgresMarketDataCatalog(postgres_dsn), OnlyClickHouseMarketFactStore(_clickhouse(database))
        )
        assert before == after
        assert len(before[1]) == 1
    finally:
        client.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")
