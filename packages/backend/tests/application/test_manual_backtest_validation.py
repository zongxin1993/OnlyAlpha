"""Real installed manual producer and durable stage recovery in canonical PG/CH.

Controlled source facts are technical preconditions. No fake VerifiedValidation,
Research publication, Shipping endpoint or business-acceptance PASS is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from packages.backend.tests.application.test_market_storage_postgres_clickhouse import (
    ROOT,
    strategy_preparation_case,
)
from packages.backend.tests.application.test_market_storage_postgres_clickhouse import (
    database as database,
)
from packages.backend.tests.application.test_strategy_research_evidence import (
    _build_strategy_evidence_owner_binary,
)
from packages.backend.tests.application.test_strategy_research_evidence import (
    market_probe as market_probe,
)
from scripts.build_algorithm_sdk import install
from scripts.dev_verification import source_inputs
from scripts.embed_build_provenance import resolve_build_provenance_bytes
from packages.backend.tests.postgres_link import wait_no_advisory_locks

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(600)]
AT = "2026-11-02T00:00:00Z"


@pytest.fixture(scope="session")
def manual_validation_owner_binary() -> Path:
    # Align the actual producer with Shipping's optimized profile. The original
    # evidence-owner fixture also uses release; sealed-image checks stay unchanged.
    return _build_strategy_evidence_owner_binary(release=True)


def _release(binary: Path, root: Path) -> tuple[Path, str, str]:
    """Use the same actual ELF for environment, graph producer and later owners."""
    root.mkdir(mode=0o700)
    artifact = install(root / "wheels", root / "algorithms")
    (root / "bin").mkdir(mode=0o700)
    selected = root / "bin/onlyalpha-backend"
    shutil.copyfile(binary, selected)
    subprocess.run(["strip", "--strip-debug", str(selected)], check=True, timeout=30)
    selected.chmod(0o500)
    (root / "source-provenance.json").write_bytes(resolve_build_provenance_bytes(ROOT))
    manifest = {
        "schema_version": 2,
        "runtime_root": str(root),
        "version": "0.11.1",
        "algorithm_artifact": artifact,
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        },
        "source_inputs": source_inputs(ROOT),
    }
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    return selected, artifact, hashlib.sha256(raw).hexdigest()


def _owner(
    binary: Path,
    dsn: str,
    research: Path,
    phase: str,
    request: dict[str, Any],
    credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = research.parent / "use_test_manual_owner_request.json"
    path.write_text(json.dumps(request))
    producer = phase.startswith("manual-producer:")
    result = subprocess.run(
        [str(binary), "--exact", "actual_command_boundary", "--nocapture"],
        cwd=ROOT,
        env={
            **os.environ,
            **(credentials or {}),
            "ONLYALPHA_POSTGRES_DSN": dsn,
            "ONLYALPHA_FREEZE_TEST_ROOT": str(research),
            "ONLYALPHA_FREEZE_TEST_PHASE": phase,
            "ONLYALPHA_MANUAL_PRODUCER_REQUEST" if producer else "ONLYALPHA_MANUAL_FREEZE_REQUEST": str(path),
        },
        capture_output=True,
        text=True,
        timeout=240 if phase == "manual-producer:produce" else 120,
    )
    original_pid = re.search(r"FREEZE_TEST_BACKEND_PID (\d+)", result.stdout)
    if original_pid is not None:
        wait_no_advisory_locks(dsn, int(original_pid.group(1)))
    assert result.returncode == 0, result.stdout + result.stderr
    marker = "MANUAL_PRODUCER_VALUE " if producer else "MANUAL_FREEZE_VALUE "
    values = [json.loads(line.removeprefix(marker)) for line in result.stdout.splitlines() if line.startswith(marker)]
    assert len(values) == 1, result.stdout + result.stderr
    value = values[0]
    assert isinstance(value, dict), "native owner must return an object"
    return value


@pytest.fixture
def actual_manual_environment(
    database: Any,
    postgres_dsn: str,
    market_probe: Path,
    manual_validation_owner_binary: Path,
    tmp_path: Path,
) -> dict[str, Any]:
    selected, artifact, release_fingerprint = _release(manual_validation_owner_binary, tmp_path / "release")
    semantic = tmp_path / "use_test_manual_semantic"
    semantic.mkdir(mode=0o700)
    vector = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    case = strategy_preparation_case(
        {"executable": market_probe, "root": tmp_path / "release", "artifact": artifact, "vector": vector},
        market_probe,
        database,
        tmp_path,
        first_bar_start=datetime(2025, 1, 2, 23, 40, tzinfo=UTC),
        runtime_root=semantic / "runtime",
        manual_only=True,
    )
    arguments = case["arguments"]
    assert arguments["strategy_context"] is None
    assert len(case["updates"]) == 740
    research = semantic / "research"
    common = {
        **arguments,
        "semantic_root": str(semantic),
        "research_root": str(research),
        "release_root": str(tmp_path / "release"),
        "algorithm_root": str(tmp_path / "release/algorithms"),
        "algorithm_artifact": artifact,
        "release_manifest_fingerprint": release_fingerprint,
        "factor": vector,
        "activation_command_id": str(uuid4()),
        "at": AT,
        "database": database.config.database,
        "url": database.config.url,
    }
    credentials = {
        "ONLYALPHA_CLICKHOUSE_USER": database.config.user,
        "ONLYALPHA_CLICKHOUSE_PASSWORD": database.config.password,
    }
    environment = _owner(selected, postgres_dsn, research, "manual-producer:environment", common, credentials)
    scope = arguments["scope"]
    common["selected_source"] = {
        "integration_id": str(uuid4()),
        "integration_revision_fingerprint": scope["bar_construction"]["plan"]["integration_revision_fingerprint"],
        "expected_type_id": "binance.spot.market_data",
        "source_id": scope["source_id"],
        "environment": "LIVE",
        "instrument_id": "BTCUSDT.BINANCE",
    }
    common["runtime_generation"] = environment["runtime_generation"]

    def produce(phase: str = "produce") -> dict[str, Any]:
        request = {**common, "preparation_command_id": str(uuid4()), "backtest_command_id": str(uuid4())}
        actual = _owner(selected, postgres_dsn, research, "manual-producer:" + phase, request, credentials)
        assert actual["state"] == "RUNNING"
        assert actual["pre_accept_observation_checks"] is True
        return actual

    # Credentials stay in the closure and never become a printed fixture value.
    return {"binary": selected, "dsn": postgres_dsn, "research": research, "produce": produce}


@pytest.fixture
def actual_manual_parents(actual_manual_environment: dict[str, Any]) -> dict[str, Any]:
    fixture = actual_manual_environment
    parents = [fixture["produce"](), fixture["produce"]()]
    assert parents[0]["preparation_command_id"] != parents[1]["preparation_command_id"]
    assert parents[0]["validation_fingerprint"] != parents[1]["validation_fingerprint"]
    assert parents[0]["strategy_fingerprint"] == parents[1]["strategy_fingerprint"]
    with psycopg.connect(fixture["dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM strategy_validation_publication").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM research_preparation WHERE state='RUNNING'").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM private_strategy_research_composition").fetchone() == (0,)
    for owner in ("calculation-results", "statistics-results", "results", "calculation-execution-evidence"):
        assert not list((fixture["research"] / owner).glob("sha256/*/*/manifest.json")), owner
    return {**fixture, "parents": parents}


@pytest.mark.parametrize("stage", ["freeze", "qualification", "promotion"])
def test_real_manual_validation_keeps_original_stage_authority_after_parent_cancellation(
    actual_manual_parents: dict[str, Any], stage: str
) -> None:
    fixture = actual_manual_parents
    a, b = fixture["parents"]

    def run(parent: dict[str, Any], phase: str) -> dict[str, Any]:
        return _owner(fixture["binary"], fixture["dsn"], fixture["research"], "manual-freeze:" + phase, parent)

    if stage == "freeze":
        denied = run(a, "cancel-before-prepared")
        assert denied["denied"] == "STRATEGY_FREEZE_PREPARATION_NOT_RUNNING"
        run(b, "stop-prepared")
        run(b, "cancel-parent")
        resumed = run(b, "resume-after-cancel")
        replayed = run(b, "replay-after-cancel")
        assert replayed["freeze_relation_fingerprint"] == resumed["freeze_relation_fingerprint"]
        run(b, "physical-replacement")
        assert run(b, "sql-denials")["sql_origin_denials"] == 7
    elif stage == "qualification":
        run(a, "freeze")
        run(b, "freeze")
        run(a, "q-cancel-before-admission")
        run(b, "q-stop-prepared")
        run(b, "cancel-parent")
        run(b, "q-resume-after-cancel")
    else:
        run(a, "freeze")
        run(b, "freeze")
        run(a, "q-qualify")
        run(b, "q-qualify")
        run(a, "p-cancel-before-admission")
        promoted = run(b, "p-promote")
        run(b, "cancel-parent")
        replayed = run(b, "p-replay-after-cancel")
        assert replayed["promotion_command_id"] == promoted["promotion_command_id"]
        with psycopg.connect(fixture["dsn"]) as conn:
            assert conn.execute("SELECT count(*) FROM strategy_promotion_record").fetchone() == (1,)
    with psycopg.connect(fixture["dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)


@pytest.mark.parametrize("producer_phase", ["produce", "bound-without-environment"])
def test_manual_cancel_cleanup_retries_after_original_runtime_owner_drains(
    actual_manual_environment: dict[str, Any], producer_phase: str
) -> None:
    fixture = actual_manual_environment
    parent = fixture["produce"](producer_phase)
    result = _owner(
        fixture["binary"],
        fixture["dsn"],
        fixture["research"],
        "manual-freeze:cleanup-eligibility-and-retry",
        parent,
    )
    assert result["environment_was_present"] is (producer_phase == "produce")
    assert result["released"] is True
    assert result["backtest_runs"] == 0
    with psycopg.connect(fixture["dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM strategy_validation_publication").fetchone() == (
            1 if producer_phase == "produce" else 0,
        )
        assert conn.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)


def test_manual_freeze_provenance_reuses_the_original_complete_backtest_grant(
    actual_manual_parents: dict[str, Any],
) -> None:
    fixture = actual_manual_parents
    first, second = fixture["parents"]

    def run(parent: dict[str, Any], phase: str) -> dict[str, Any]:
        return _owner(fixture["binary"], fixture["dsn"], fixture["research"], "manual-freeze:" + phase, parent)

    with psycopg.connect(fixture["dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM strategy_catalog").fetchone() == (0,)
    original_freeze = run(first, "freeze")
    assert run(first, "reuse-absent") == {"grant": None}
    run(first, "q-qualify")
    run(first, "p-promote")
    original_grant = run(first, "reuse-existing")
    later_freeze = run(second, "freeze")
    assert original_freeze["strategy_fingerprint"] == later_freeze["strategy_fingerprint"]
    assert original_freeze["freeze_relation_fingerprint"] != later_freeze["freeze_relation_fingerprint"]
    assert original_grant["freeze_relation_fingerprint"] == original_freeze["freeze_relation_fingerprint"]
    assert run(second, "reuse-existing") == original_grant
    with psycopg.connect(fixture["dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM strategy_freeze_record").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM strategy_promotion_record").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM qualification_command_admission").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        conn.execute("UPDATE strategy_catalog SET schema_version=2")
    assert run(second, "reuse-corrupt-catalog") == {"denied": "PROMOTION_LEDGER_CORRUPT"}
    with psycopg.connect(fixture["dsn"]) as conn:
        conn.execute("UPDATE strategy_catalog SET schema_version=1")
    assert run(second, "reuse-existing") == original_grant
    with psycopg.connect(fixture["dsn"]) as conn:
        receipt = conn.execute(
            "SELECT command_id::text FROM product_command_receipt WHERE outcome_kind='STRATEGY_PROMOTION' AND outcome_id=%s",
            (original_grant["promotion_fingerprint"],),
        ).fetchone()
        assert receipt is not None
    # Deliberate physical corruption in the isolated test namespace. Restore
    # every original row exactly; neither reader may repair or mint a grant.
    for table, key, identity in [
        ("strategy_promotion_record", "promotion_record_fingerprint", original_grant["promotion_fingerprint"]),
        ("strategy_freeze_record", "freeze_record_fingerprint", original_grant["freeze_relation_fingerprint"]),
        (
            "qualification_command_admission",
            "decision_fingerprint",
            original_grant["qualification_decision_fingerprint"],
        ),
        ("product_command_receipt", "command_id", receipt[0]),
    ]:
        with psycopg.connect(fixture["dsn"]) as conn:
            saved = conn.execute(f"SELECT to_jsonb(t) FROM {table} t WHERE {key}=%s", (identity,)).fetchone()
            assert saved is not None and isinstance(saved[0], dict)
            record = saved[0]
            conn.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            conn.execute(f"DELETE FROM {table} WHERE {key}=%s", (identity,))
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            conn.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        try:
            denied = run(
                {
                    **second,
                    "selected_grant": original_grant,
                    "standalone_denied": table == "qualification_command_admission",
                },
                "selected-denied",
            )
            assert set(denied) == {"denied"} and isinstance(denied["denied"], str)
            with psycopg.connect(fixture["dsn"]) as conn:
                assert conn.execute(f"SELECT count(*) FROM {table} WHERE {key}=%s", (identity,)).fetchone() == (0,)
        finally:
            with psycopg.connect(fixture["dsn"]) as conn:
                conn.execute(
                    f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table},%s)).*", (Jsonb(record),)
                )
                assert conn.execute(f"SELECT to_jsonb(t) FROM {table} t WHERE {key}=%s", (identity,)).fetchone() == (
                    record,
                )
    assert run(second, "reuse-existing") == original_grant
