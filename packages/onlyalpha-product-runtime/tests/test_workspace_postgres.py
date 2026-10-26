"""Technical configuration-authority checks; never Shipping UI acceptance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def workspace_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def config() -> dict[str, Any]:
    return {
        "source": {
            "integration_id": "source",
            "integration_revision_fingerprint": "a" * 64,
            "expected_type_id": "test.source",
        },
        "instrument_id": "BTCUSDT.BINANCE",
        "bar_semantic": {
            "schema_version": 3,
            "formation": {
                "schema_version": 1,
                "kind": "FIXED_DURATION",
                "window_minutes": 7,
                "stride_minutes": 7,
                "alignment": "SESSION_START",
            },
            "price_type": "LAST",
            "adjustment_policy": "RAW",
        },
        "studies": [],
    }


def run(
    probe: Path,
    operation: str,
    namespace: str,
    *,
    command: str | None = None,
    version: int = 0,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "op": "workspace-" + operation,
        "namespace_id": namespace,
        "command_id": command or str(uuid4()),
        "expected_version": version,
        "configuration": configuration or config(),
        "accepted_at": "2026-10-24T00:00:00Z",
    }
    result = subprocess.run([str(probe)], input=json.dumps(payload), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_workspace_cas_restart_and_exact_historical_receipt(native_probe: Path, workspace_db: str) -> None:
    ns = str(uuid4())
    original = str(uuid4())
    assert run(native_probe, "read", ns) == {"book": {"version": 0, "configuration": None}}
    first = run(native_probe, "save", ns, command=original)
    assert first == {"book": {"version": 1, "configuration": config()}}
    changed = config()
    changed["instrument_id"] = "ETHUSDT.BINANCE"
    assert run(native_probe, "save", ns, version=1, configuration=changed) == {
        "book": {"version": 2, "configuration": changed}
    }
    assert run(native_probe, "save", ns, command=original) == first
    assert run(native_probe, "command", ns, command=original) == first
    assert run(native_probe, "save", ns, command=original, configuration=changed) == {
        "error": "WORKSPACE_COMMAND_CONFLICT"
    }
    losing = str(uuid4())
    assert run(native_probe, "save", ns, command=losing) == {"error": "WORKSPACE_VERSION_CONFLICT"}
    with psycopg.connect(workspace_db) as db:
        assert db.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (losing,)
        ).fetchone() == (0,)
    assert run(native_probe, "read", ns) == {"book": {"version": 2, "configuration": changed}}
    assert run(native_probe, "command", str(uuid4()), command=original) == {"error": "WORKSPACE_HISTORY_CORRUPT"}


def test_workspace_unknown_and_cross_kind_never_resubmit(native_probe: Path, workspace_db: str) -> None:
    ns = str(uuid4())
    command = str(uuid4())
    fp = "a" * 64
    with psycopg.connect(workspace_db) as db:
        db.execute(
            "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,'SAVE_WORKSPACE',%s,1)",
            (command, fp),
        )
    assert run(native_probe, "command", ns, command=command) == {"error": "WORKSPACE_COMMAND_UNKNOWN"}
    assert run(native_probe, "save", ns, command=command) == {"error": "WORKSPACE_COMMAND_CONFLICT"}
    assert run(native_probe, "read", ns) == {"book": {"version": 0, "configuration": None}}
    with psycopg.connect(workspace_db) as db:
        db.execute(
            "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,'SAVE_WATCHLISTS',%s,1)",
            (other := str(uuid4()), fp),
        )
    assert run(native_probe, "command", ns, command=other) == {"error": "WORKSPACE_COMMAND_CONFLICT"}


def test_workspace_immutable_revision_and_missing_head_fail_closed(native_probe: Path, workspace_db: str) -> None:
    ns = str(uuid4())
    run(native_probe, "save", ns)
    with pytest.raises(psycopg.Error), psycopg.connect(workspace_db) as db:
        db.execute("UPDATE workspace_revision SET configuration_json='{}' WHERE namespace_id=%s", (ns,))
    with psycopg.connect(workspace_db) as db:
        db.execute("DELETE FROM workspace_head WHERE namespace_id=%s", (ns,))
    assert run(native_probe, "read", ns) == {"error": "WORKSPACE_HISTORY_CORRUPT"}


def test_workspace_study_intent_roundtrips_without_numeric_results(native_probe: Path, workspace_db: str) -> None:
    ns = str(uuid4())
    configuration = config()
    configuration["studies"] = [
        {
            "kind": "INDICATOR",
            "type_id": "test.bollinger",
            "semantic_version": "1",
            "parameters": {
                "period": {"type": "INTEGER", "value": 20},
                "deviation": {"type": "DECIMAL", "value": "2.00"},
            },
            "output_names": ["upper"],
            "presentation": {
                "placement": "PRICE_OVERLAY",
                "color": "#abcdef",
                "line_width": 2.5,
                "opacity": 0.6,
                "visible": False,
                "series_styles": {"lower": {"color": "#123456", "visible": False}},
            },
        }
    ]
    expected = {"book": {"version": 1, "configuration": configuration}}
    command = str(uuid4())
    assert run(native_probe, "save", ns, command=command, configuration=configuration) == expected
    assert run(native_probe, "read", ns) == expected
    assert run(native_probe, "save", ns, command=command, configuration=configuration) == expected
    assert run(native_probe, "command", ns, command=command) == expected
