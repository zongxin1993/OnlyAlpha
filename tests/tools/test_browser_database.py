from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from onlyalpha.persistence.clickhouse import OnlyClickHouseClient, OnlyClickHouseConfig
from tests.support import browser_database


def _operation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker = tmp_path / "source-cut.json"
    marker.write_text(json.dumps({"operation_id": "current-operation", "source_root": str(tmp_path)}))
    monkeypatch.setattr(browser_database, "RUN_METADATA", marker)
    monkeypatch.setenv("ONLYALPHA_DEV_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "current-operation")


@pytest.mark.parametrize("namespace", sorted(browser_database.CLICKHOUSE_NAMESPACES))
def test_dev_browser_reset_is_exact_serialized_and_repeatable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, namespace: str
) -> None:
    _operation(monkeypatch, tmp_path)
    clickhouse = OnlyClickHouseClient(OnlyClickHouseConfig("http://clickhouse:8123", database=namespace))
    writes: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        clickhouse, "execute", lambda statement, **kwargs: writes.append((statement, kwargs.get("database")))
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (True,)
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(browser_database.psycopg, "connect", connect)
    for _ in range(2):
        browser_database.reset_dev_browser_test_namespace(browser_database.DEV_TEST_DSN, clickhouse)
    assert writes == [(f"DROP DATABASE IF EXISTS {namespace} SYNC", "default")] * 2
    assert [call.args[0] for call in connection.execute.call_args_list] == [
        "SELECT pg_try_advisory_xact_lock(71493012)",
        "DROP SCHEMA public CASCADE",
        "CREATE SCHEMA public",
    ] * 2
    assert all(call.args == (browser_database.DEV_TEST_DSN,) for call in connect.call_args_list)


@pytest.mark.parametrize(
    "mutation",
    [
        "business-pg",
        "other-test-pg",
        "external-pg",
        "business-ch",
        "other-test-ch",
        "external-ch",
        "missing-operation",
        "wrong-operation",
        "wrong-source-root",
        "missing-source-root",
        "marker-only-missing-operation",
        "marker-only-missing-source-root",
        "missing-marker",
        "malformed-marker",
    ],
)
def test_browser_reset_refuses_wrong_or_incomplete_context_before_any_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    _operation(monkeypatch, tmp_path)
    dsn = browser_database.DEV_TEST_DSN
    namespace, url = "onlyalpha_test_chart_study_browser", "http://clickhouse:8123"
    if mutation == "business-pg":
        dsn = dsn.removesuffix("_test")
    elif mutation == "other-test-pg":
        dsn = dsn.replace("onlyalpha_dev_validation_test", "other_test")
    elif mutation == "external-pg":
        dsn = dsn.replace("@postgres:", "@external:")
    elif mutation == "business-ch":
        namespace = "onlyalpha"
    elif mutation == "other-test-ch":
        namespace = "onlyalpha_test_other"
    elif mutation == "external-ch":
        url = "http://external:8123"
    clickhouse = OnlyClickHouseClient(OnlyClickHouseConfig(url, database=namespace))
    monkeypatch.setattr(clickhouse, "execute", lambda *a, **k: pytest.fail("ClickHouse must not be touched"))
    monkeypatch.setattr(
        browser_database.psycopg, "connect", lambda *a, **k: pytest.fail("PostgreSQL must not be touched")
    )
    if mutation == "missing-operation":
        monkeypatch.delenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID")
    elif mutation == "wrong-operation":
        monkeypatch.setenv("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID", "other-operation")
    elif mutation == "wrong-source-root":
        monkeypatch.setenv("ONLYALPHA_DEV_SOURCE_ROOT", str(tmp_path / "other"))
    elif mutation == "missing-source-root":
        monkeypatch.delenv("ONLYALPHA_DEV_SOURCE_ROOT")
        browser_database.RUN_METADATA.write_text(json.dumps({"operation_id": "current-operation"}))
    elif mutation == "marker-only-missing-operation":
        browser_database.RUN_METADATA.write_text(json.dumps({"source_root": str(tmp_path)}))
    elif mutation == "marker-only-missing-source-root":
        browser_database.RUN_METADATA.write_text(json.dumps({"operation_id": "current-operation"}))
    elif mutation == "missing-marker":
        browser_database.RUN_METADATA.unlink()
    elif mutation == "malformed-marker":
        browser_database.RUN_METADATA.write_text("not-json")
    error = RuntimeError if mutation == "business-pg" else ValueError
    if mutation == "missing-marker":
        error = FileNotFoundError
    with pytest.raises(error):
        browser_database.reset_dev_browser_test_namespace(dsn, clickhouse)


def test_busy_database_lock_refuses_before_destructive_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _operation(monkeypatch, tmp_path)
    clickhouse = OnlyClickHouseClient(
        OnlyClickHouseConfig("http://clickhouse:8123", database="onlyalpha_test_chart_study_browser")
    )
    monkeypatch.setattr(clickhouse, "execute", lambda *a, **k: pytest.fail("no reset while busy"))
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (False,)
    monkeypatch.setattr(browser_database.psycopg, "connect", MagicMock(return_value=connection))
    with pytest.raises(ValueError, match="BROWSER_TEST_RESET_BUSY"):
        browser_database.reset_dev_browser_test_namespace(browser_database.DEV_TEST_DSN, clickhouse)
    assert connection.execute.call_count == 1


@pytest.mark.parametrize("failure", ["lost-ch-response", "lost-pg-commit"])
def test_uncertain_reset_retains_fence_and_refuses_repeat_without_network_or_seed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    _operation(monkeypatch, tmp_path)
    fence = tmp_path / browser_database.BROWSER_RESET_FENCE
    clickhouse = OnlyClickHouseClient(
        OnlyClickHouseConfig("http://clickhouse:8123", database="onlyalpha_test_chart_study_browser")
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (True,)
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(browser_database.psycopg, "connect", connect)

    def destructive(statement: str, **kwargs: object) -> str:
        assert fence.exists(), "UNKNOWN must be durable before remote destruction is submitted"
        assert json.loads(fence.read_text())["operation_id"] == "current-operation"
        if failure == "lost-ch-response":
            raise RuntimeError("CLICKHOUSE_RESPONSE_LOST_AFTER_ACCEPTANCE")
        return ""

    monkeypatch.setattr(clickhouse, "execute", destructive)
    if failure == "lost-pg-commit":
        connection.__exit__.side_effect = psycopg.OperationalError("COMMIT_RESPONSE_LOST")
    with pytest.raises(RuntimeError if failure == "lost-ch-response" else psycopg.OperationalError):
        browser_database.reset_dev_browser_test_namespace(browser_database.DEV_TEST_DSN, clickhouse)
    assert json.loads(fence.read_text())["outcome"] == "UNKNOWN"
    if failure == "lost-ch-response":
        assert connection.execute.call_count == 1, "PostgreSQL reset must not follow an unproved CH outcome"
    with pytest.raises(ValueError, match="UNKNOWN_REQUIRES_OWNER_RECOVERY"):
        browser_database.reset_dev_browser_test_namespace(browser_database.DEV_TEST_DSN, clickhouse)
    assert connect.call_count == 1
