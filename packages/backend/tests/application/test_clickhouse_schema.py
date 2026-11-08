"""Real isolated warehouse initialization uses the owning Rust executable."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.parse
import urllib.request
import uuid

import pytest

from scripts.native_http_contract import native_executable
from scripts.native_web_e2e import clickhouse_namespace

pytestmark = pytest.mark.clickhouse


def _query(database: str, statement: str) -> list[dict[str, object]]:
    request = urllib.request.Request(
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"].rstrip("/") + "?" + urllib.parse.urlencode({"database": database}),
        data=(statement + " FORMAT JSONEachRow").encode(),
        method="POST",
    )
    credentials = os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"] + ":" + os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"]
    request.add_header("Authorization", "Basic " + base64.b64encode(credentials.encode()).decode())
    with urllib.request.urlopen(request, timeout=5) as response:
        return [json.loads(line) for line in response.read().decode().splitlines() if line]


def test_fresh_rust_schema_has_exact_history_and_never_adopts_an_existing_database() -> None:
    backend = native_executable(release=False)
    database = "onlyalpha_test_schema_" + uuid.uuid4().hex
    count_database = f"SELECT count() AS n FROM system.databases WHERE name='{database}'"
    assert _query("default", count_database) == [{"n": 0}]
    clickhouse_namespace(backend, database, initialize=False)
    assert _query("default", count_database) == [{"n": 0}]
    clickhouse_namespace(backend, database, initialize=True)
    try:
        expected = [
            {
                "migration_id": "0001_market_data_foundation",
                "checksum_sha256": "4daa95922af511fe124a5eed1c17d4d0877fa5298340db5a9d0330b7a380be9e",
            },
            {
                "migration_id": "0002_market_data_integration_runtime_provenance",
                "checksum_sha256": "97878e76c396f7f29abb6649e98be0aa2a71e84dbc4c4fdce0584633327176c4",
            },
        ]
        statement = "SELECT migration_id, checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
        assert _query(database, statement) == expected
        assert _query(
            database,
            "SELECT count() AS n FROM system.columns WHERE database=currentDatabase() AND table='market_raw_event' AND name='integration_binding_fingerprint'",
        ) == [{"n": 1}]
        duplicate = subprocess.run(
            [str(backend), "--initialize-test-clickhouse", database], capture_output=True, text=True, check=False
        )
        assert duplicate.returncode != 0
        assert not duplicate.stdout.strip()
        assert _query(database, statement) == expected
    finally:
        clickhouse_namespace(backend, database, initialize=False)
    assert _query("default", count_database) == [{"n": 0}]
    clickhouse_namespace(backend, database, initialize=False)
    assert _query("default", count_database) == [{"n": 0}]


def test_rust_schema_invalid_policy_cannot_leave_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = native_executable(release=False)
    database = "onlyalpha_test_invalid_schema_" + uuid.uuid4().hex
    monkeypatch.setenv("ONLYALPHA_TEST_CLICKHOUSE_STORAGE_POLICY", "default'; DROP DATABASE onlyalpha; --")
    result = subprocess.run(
        [str(backend), "--initialize-test-clickhouse", database], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "MARKET_DATA_INPUT_INVALID" in result.stderr
    assert _query("default", f"SELECT count() AS n FROM system.databases WHERE name='{database}'") == [{"n": 0}]
