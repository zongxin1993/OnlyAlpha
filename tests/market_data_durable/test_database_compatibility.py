from __future__ import annotations

from dataclasses import replace

import pytest

from onlyalpha.persistence.clickhouse import (
    OnlyClickHouseConfig,
    OnlyClickHouseMarketFactStore,
    OnlyClickHouseServerVersion,
    only_assert_clickhouse_test_database,
    only_assert_supported_clickhouse_server,
)
from onlyalpha.persistence.postgres import (
    ONLYALPHA_POSTGRES_CLIENT_MAJOR,
    ONLYALPHA_POSTGRES_SERVER_MAJOR,
    OnlyPostgresMarketDataCatalog,
    OnlyPostgresServerVersion,
    only_assert_postgres_test_database,
)


class _VersionClient:
    def __init__(self, version: str) -> None:
        self.version = version

    def query_json(self, _sql: str, *, database: str | None = None) -> tuple[dict[str, object], ...]:
        assert database == "default"
        return ({"version": self.version},)


def test_frozen_database_version_families_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (ONLYALPHA_POSTGRES_SERVER_MAJOR, ONLYALPHA_POSTGRES_CLIENT_MAJOR) == (18, 18)
    assert only_assert_supported_clickhouse_server(_VersionClient("26.3.2.1")).version == "26.3.2.1"  # type: ignore[arg-type]
    for unsupported in ("25.8.12.1", "26.4.1.1", "27.3.1.1", "unknown"):
        with pytest.raises(RuntimeError, match="CLICKHOUSE_SERVER_(FAMILY_UNSUPPORTED|VERSION_INVALID)"):
            only_assert_supported_clickhouse_server(_VersionClient(unsupported))  # type: ignore[arg-type]

    inspected = OnlyPostgresServerVersion("18.6", 18)
    monkeypatch.setattr("onlyalpha.persistence.postgres.version.only_postgres_server_version", lambda _dsn: inspected)
    from onlyalpha.persistence.postgres.version import only_assert_supported_postgres_server

    assert only_assert_supported_postgres_server("postgresql://redacted") == inspected
    for major in (16, 19):
        monkeypatch.setattr(
            "onlyalpha.persistence.postgres.version.only_postgres_server_version",
            lambda _dsn, major=major: replace(inspected, version=f"{major}.0", major=major),
        )
        with pytest.raises(RuntimeError, match="POSTGRES_SERVER_MAJOR_UNSUPPORTED"):
            only_assert_supported_postgres_server("postgresql://redacted")


def test_market_data_runtime_owners_reject_unsupported_database_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="CLICKHOUSE_SERVER_FAMILY_UNSUPPORTED"):
        OnlyClickHouseMarketFactStore(_VersionClient("26.4.1.1"))  # type: ignore[arg-type]
    monkeypatch.setattr(
        "onlyalpha.persistence.postgres.market_data_catalog.only_assert_supported_postgres_server",
        lambda _dsn: (_ for _ in ()).throw(RuntimeError("POSTGRES_SERVER_MAJOR_UNSUPPORTED")),
    )
    with pytest.raises(RuntimeError, match="POSTGRES_SERVER_MAJOR_UNSUPPORTED"):
        OnlyPostgresMarketDataCatalog("postgresql://redacted")


def test_database_test_and_restore_names_cannot_target_production() -> None:
    assert only_assert_postgres_test_database("postgresql://host/onlyalpha_test") == "onlyalpha_test"
    assert (
        only_assert_postgres_test_database("postgresql://host/onlyalpha_restore_test", restore=True)
        == "onlyalpha_restore_test"
    )
    assert only_assert_clickhouse_test_database("onlyalpha_test_run1") == "onlyalpha_test_run1"
    assert only_assert_clickhouse_test_database("onlyalpha_restore_run1", restore=True) == "onlyalpha_restore_run1"
    with pytest.raises(RuntimeError, match="POSTGRES_INTEGRATION_TEST_DATABASE_REQUIRED"):
        only_assert_postgres_test_database("postgresql://host/onlyalpha")
    with pytest.raises(RuntimeError, match="POSTGRES_RESTORE_TEST_DATABASE_REQUIRED"):
        only_assert_postgres_test_database("postgresql://host/onlyalpha_test", restore=True)
    with pytest.raises(RuntimeError, match="CLICKHOUSE_TEST_DATABASE_REQUIRED"):
        only_assert_clickhouse_test_database("onlyalpha")
    with pytest.raises(RuntimeError, match="CLICKHOUSE_RESTORE_DATABASE_REQUIRED"):
        only_assert_clickhouse_test_database("onlyalpha_test_run1", restore=True)


def test_clickhouse_config_requires_explicit_environment_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONLYALPHA_CLICKHOUSE_URL", raising=False)
    with pytest.raises(ValueError, match="ONLYALPHA_CLICKHOUSE_URL is required"):
        OnlyClickHouseConfig.from_environment()
    config = OnlyClickHouseConfig("http://clickhouse:8123", password="never-print-this")
    assert "never-print-this" not in repr(config)
    assert "credentials=<redacted>" in repr(config)


def test_clickhouse_version_parser_accepts_only_numeric_server_versions() -> None:
    assert OnlyClickHouseServerVersion.parse("26.3.1.4") == OnlyClickHouseServerVersion("26.3.1.4", 26, 3, 1)
    with pytest.raises(RuntimeError, match="CLICKHOUSE_SERVER_VERSION_INVALID"):
        OnlyClickHouseServerVersion.parse("26.3")
