from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyMarketDataIngress,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)
from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseClient,
    OnlyClickHouseConfig,
    OnlyClickHouseError,
    OnlyClickHouseMarketFactStore,
    OnlyClickHouseMigrationAuthority,
    only_assert_clickhouse_test_database,
)
from onlyalpha.persistence.clickhouse.market_data_store import _PHYSICAL_COLUMNS, _physical_row_proof, _physical_row_sql
from scripts.market_data_database import _backup_segment, _restore_segment

from .conftest import BASE, INSTRUMENT, trade_update
from .test_wal_and_identity import observation

pytestmark = [pytest.mark.clickhouse, pytest.mark.external, pytest.mark.requires_network]


@pytest.fixture
def clickhouse_client() -> OnlyClickHouseClient:
    url = os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_URL")
    if not url:
        pytest.fail("ONLYALPHA_TEST_CLICKHOUSE_URL is required for ClickHouse integration")
    database = os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_DATABASE", f"onlyalpha_test_{uuid.uuid4().hex}")
    only_assert_clickhouse_test_database(database)
    config = OnlyClickHouseConfig(
        url,
        database=database,
        user=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
        password=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
        storage_policy=os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "hot_cold"),
    )
    client = OnlyClickHouseClient(config)
    try:
        yield client
    finally:
        client.execute(f"DROP DATABASE IF EXISTS {database} SYNC", database="default")


class _LostAcknowledgementClient:
    def __init__(self, client: OnlyClickHouseClient, table: str) -> None:
        self._client = client
        self.config = client.config
        self._table = table
        self._lost = False

    def insert_json_each_row(self, table: str, rows) -> None:  # type: ignore[no-untyped-def]
        self._client.insert_json_each_row(table, rows)
        if table == self._table and not self._lost:
            self._lost = True
            raise OnlyClickHouseError("INJECTED_ACK_LOSS")

    def query_json(self, sql: str, *, database: str | None = None):  # type: ignore[no-untyped-def]
        return self._client.query_json(sql, database=database)


def _segment(root: Path, fixed_now, *, sequence: int = 10, segment_id: str = "segment-ch"):  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(root, capacity_bytes=1_000_000, now=fixed_now, identity_factory=lambda: segment_id)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 123456789
    )
    ingress.begin_segment()
    event = replace(
        observation(f'{{"e":"trade","t":{sequence}}}'.encode()),
        provider_event_id=str(sequence),
        provider_sequence=sequence,
    )
    ingress.record(event, trade_update(sequence, price="100.12000000"))
    segment = ingress.seal()
    return segment, wal.read_sealed(segment.segment_id)


def test_clickhouse_batch_verifies_many_one_record_segments_and_reads_in_order(
    clickhouse_client: OnlyClickHouseClient, tmp_path: Path, fixed_now
) -> None:
    OnlyClickHouseMigrationAuthority(clickhouse_client).migrate()
    for table, columns in _PHYSICAL_COLUMNS.items():
        actual = clickhouse_client.query_json(
            f"SELECT name FROM system.columns WHERE database=currentDatabase() AND table='{table}' ORDER BY position"
        )
        assert tuple(row["name"] for row in actual) == tuple(name for name, _ in columns)
    store = OnlyClickHouseMarketFactStore(clickhouse_client)
    segments = []
    records_by_segment = {}
    for index in range(10):
        segment, records = _segment(
            tmp_path / str(index), fixed_now, sequence=100 + index, segment_id=f"segment-batch-{index}"
        )
        store.write_segment(segment, records)
        segments.append(segment)
        records_by_segment[segment.segment_id] = records
    base_ns = int(BASE.timestamp() * 1_000_000_000)
    scope = OnlyMarketDataScope(
        "BINANCE_SPOT",
        "SPOT",
        str(INSTRUMENT),
        "TRADE",
        base_ns,
        base_ns + 200_000_000_000,
        "BINANCE_SPOT_V1",
        None,
        100,
        109,
    )

    proofs = store.verify_segments(tuple(segments), records_by_segment, scope).physical_proofs
    facts = store.read_segment_facts(tuple(segments), scope, proofs)

    assert [item.canonical_payload["source_sequence"] for item in facts] == list(range(100, 110))


def test_physical_row_encoding_matches_clickhouse_for_nullable_decimal_and_unicode(
    clickhouse_client: OnlyClickHouseClient, tmp_path: Path, fixed_now
) -> None:
    OnlyClickHouseMigrationAuthority(clickhouse_client).migrate()
    segment, records = _segment(tmp_path, fixed_now, segment_id="physical-encoding")
    store = OnlyClickHouseMarketFactStore(clickhouse_client)
    for index, nullable in enumerate((None, "", "NULL")):
        row = store._raw_row(segment, index, records[0])
        row.update(
            raw_event_id=f"encoding-{index}",
            provider_event_id=nullable,
            provider_sequence=-1,
            ts_event_ns=8_000_000_000_000_000_000,
            provider_schema="值:|\n😀",
        )
        clickhouse_client.insert_json_each_row("market_raw_event", (row,))
        actual = clickhouse_client.query_json(
            f"SELECT {_physical_row_sql('market_raw_event')} AS proof FROM market_raw_event "
            f"WHERE raw_event_id='encoding-{index}'"
        )
        assert actual == ({"proof": _physical_row_proof("market_raw_event", row)},)
    trade = store._fact_row(segment, records[0].canonical_facts[0])
    trade.update(price="-123.450000000000000001", quantity="0.000000000000000001", aggressor_side="值:|😀")
    clickhouse_client.insert_json_each_row("market_trade", (trade,))
    actual = clickhouse_client.query_json(
        f"SELECT {_physical_row_sql('market_trade')} AS proof FROM market_trade WHERE segment_id='physical-encoding'"
    )
    assert actual == ({"proof": _physical_row_proof("market_trade", trade)},)


def test_clickhouse_migration_unknown_write_exact_round_trip_and_configured_storage(
    clickhouse_client: OnlyClickHouseClient, tmp_path: Path, fixed_now
) -> None:
    authority = OnlyClickHouseMigrationAuthority(clickhouse_client)
    expected_migrations = (
        "0001_market_data_foundation",
        "0002_market_data_integration_runtime_provenance",
    )
    assert tuple(item.migration_id for item in authority.plan()) == expected_migrations
    assert authority.migrate() == expected_migrations
    authority.validate()

    partial_segment, partial_records = _segment(tmp_path / "partial", fixed_now)
    partial = OnlyClickHouseMarketFactStore(
        _LostAcknowledgementClient(clickhouse_client, "market_raw_event")  # type: ignore[arg-type]
    )
    with pytest.raises(OnlyClickHouseError, match="INJECTED_ACK_LOSS"):
        partial.write_segment(partial_segment, partial_records)
    assert partial.inspect_segment(partial_segment) == "PARTIAL"

    segment, records = _segment(tmp_path / "exact", fixed_now)
    segment = replace(segment, segment_id="segment-ch-exact")
    records = tuple(
        replace(
            bundle,
            canonical_facts=tuple(replace(fact, segment_id=segment.segment_id) for fact in bundle.canonical_facts),
        )
        for bundle in records
    )
    lossy = _LostAcknowledgementClient(clickhouse_client, "market_trade")
    store = OnlyClickHouseMarketFactStore(lossy)  # type: ignore[arg-type]
    with pytest.raises(OnlyClickHouseError, match="INJECTED_ACK_LOSS"):
        store.write_segment(segment, records)
    assert store.inspect_segment(segment) == "EXACT"
    store.verify_segment(segment, records)

    base_ns = int(BASE.timestamp() * 1_000_000_000)
    scope = OnlyMarketDataScope(
        "BINANCE_SPOT",
        "SPOT",
        str(INSTRUMENT),
        "TRADE",
        base_ns,
        base_ns + 60_000_000_000,
        "BINANCE_SPOT_V1",
        None,
        10,
        10,
    )
    catalog = OnlyInMemoryMarketDataCatalog()
    revision = OnlyRevisionCommitService(store, catalog, now=fixed_now).commit(
        segment, scope, {segment.segment_id: records}
    )[1]
    [fact] = OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision.revision_id, scope)
    assert fact == records[0].canonical_facts[0]

    [stored] = clickhouse_client.query_json(
        "SELECT toString(price) AS price, price_precision, ts_event_ns, ts_receive_ns, ts_ingest_ns "
        "FROM market_trade WHERE segment_id='segment-ch-exact'"
    )
    assert stored == {
        "price": "100.12",
        "price_precision": 8,
        "ts_event_ns": records[0].canonical_facts[0].ts_event_ns,
        "ts_receive_ns": records[0].canonical_facts[0].ts_receive_ns,
        "ts_ingest_ns": 123456789,
    }

    before = clickhouse_client.query_json(
        "SELECT count() AS count, groupBitXor(cityHash64(tuple(*))) AS hash FROM market_trade"
    )
    if clickhouse_client.config.storage_policy == "hot_cold":
        clickhouse_client.execute("ALTER TABLE market_trade MOVE PARTITION 202601 TO VOLUME 'cold'")
    else:
        assert clickhouse_client.config.storage_policy == "default"
        clickhouse_client.execute("OPTIMIZE TABLE market_trade FINAL")
    after = clickhouse_client.query_json(
        "SELECT count() AS count, groupBitXor(cityHash64(tuple(*))) AS hash FROM market_trade"
    )
    assert after == before

    backup = tmp_path / "segment-ch.json"
    _backup_segment(clickhouse_client, segment.segment_id, backup)
    restore_database = os.environ.get(
        "ONLYALPHA_TEST_CLICKHOUSE_RESTORE_DATABASE", f"onlyalpha_restore_{uuid.uuid4().hex}"
    )
    only_assert_clickhouse_test_database(restore_database, restore=True)
    restored_client = OnlyClickHouseClient(
        OnlyClickHouseConfig(
            clickhouse_client.config.url,
            database=restore_database,
            user=clickhouse_client.config.user,
            password=clickhouse_client.config.password,
            storage_policy=clickhouse_client.config.storage_policy,
        )
    )
    try:
        OnlyClickHouseMigrationAuthority(restored_client).migrate()
        _restore_segment(restored_client, backup)
        restored = restored_client.query_json(
            "SELECT count() AS count, groupBitXor(cityHash64(tuple(*))) AS hash FROM market_trade"
        )
        assert restored == before
    finally:
        restored_client.execute(f"DROP DATABASE IF EXISTS {restore_database} SYNC", database="default")
