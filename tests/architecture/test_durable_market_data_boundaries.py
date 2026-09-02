from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def _source(root: Path) -> str:
    return "\n".join(path.read_text() for path in root.rglob("*.py"))


def test_provider_captures_opaque_evidence_without_database_dependencies() -> None:
    provider = Path("plugs/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance")
    source = _source(provider)
    assert "provider_evidence_sink" in source
    assert "OnlyRawProviderObservation" in source
    for forbidden in (
        "onlyalpha.persistence.clickhouse",
        "onlyalpha.persistence.postgres",
        "psycopg",
        "ClickHouseClient",
    ):
        assert forbidden not in source


def test_production_composition_cannot_silently_bypass_durable_recorder() -> None:
    composition = Path("src/onlyalpha/runtime/sim/factory.py").read_text()
    provider_factory = Path(
        "plugs/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/spot/data_source/factory.py"
    ).read_text()
    assert "durable_recording_required=True" in composition
    assert "provider_evidence_sink=durable_recorder" in composition
    assert "DURABLE_MARKET_DATA_RECORDER_REQUIRED" in provider_factory


def test_durable_core_is_provider_neutral_and_research_has_no_mutable_clickhouse_path() -> None:
    durable = _source(Path("src/onlyalpha/market_data/durable"))
    research = _source(Path("src/onlyalpha/research"))
    assert "onlyalpha_plugin_binance" not in durable
    assert "onlyalpha.persistence" not in durable
    assert "persistence.clickhouse" not in research
    assert "SELECT * FROM market_" not in research
    backfill = Path("src/onlyalpha/market_data/durable/backfill.py").read_text()
    assert "OnlyHistoricalDataSource" in backfill
    assert "api/v3" not in backfill
    assert "ClickHouse" not in backfill
    assert "Postgres" not in backfill
    assert "historical_cache" not in durable


def test_revision_and_wal_authorities_are_append_only_and_not_timing_luck() -> None:
    durable = _source(Path("src/onlyalpha/market_data/durable"))
    postgres = Path("database/postgres/migrations/0013_market_data_catalog.sql").read_text()
    clickhouse = Path("database/clickhouse/migrations/0001_market_data_foundation.sql").read_text()
    assert "SEALED_REVISION_IMMUTABLE" in durable
    assert "reject_mutation" in postgres
    assert "UPDATE market_data_revision" not in postgres
    assert "ReplacingMergeTree" not in clickhouse
    assert "TTL DELETE" not in clickhouse
    assert "sleep(" not in durable


def test_clickhouse_and_postgres_authority_split_is_typed_and_explicit() -> None:
    clickhouse = Path("database/clickhouse/migrations/0001_market_data_foundation.sql").read_text()
    postgres = Path("database/postgres/migrations/0013_market_data_catalog.sql").read_text()
    for table in ("market_raw_event", "market_trade", "market_bar", "market_reference_price"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in clickhouse
        assert f"CREATE TABLE {table}" not in postgres
    for table in ("market_coverage_manifest", "market_data_revision", "market_revision_seal"):
        assert f"CREATE TABLE {table}" in postgres
        assert f"CREATE TABLE IF NOT EXISTS {table}" not in clickhouse
    assert "async_insert=0" in Path("src/onlyalpha/persistence/clickhouse/client.py").read_text()
    assert "storage_policy = '{storage_policy}'" in clickhouse


def test_scope_did_not_expand_to_futures_or_depth() -> None:
    changed_surface = (
        _source(Path("src/onlyalpha/market_data/durable"))
        + Path("database/clickhouse/migrations/0001_market_data_foundation.sql").read_text()
    )
    for forbidden in ("market_depth", "market_book", "USD_M", "FUTURES", "QMT", "CTP"):
        assert forbidden not in changed_surface
