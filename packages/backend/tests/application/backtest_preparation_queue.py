"""Actual queue admission over existing completed science. No READY/UI claim."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest


def exercise_backtest_preparation_queue(
    binary: Path,
    dsn: str,
    root: Path,
    common: dict[str, Any],
    frozen: dict[str, Any],
    report: dict[str, Any],
    evidence_paths: list[Path],
) -> None:
    from tests.support.postgres_link import wait_no_advisory_locks

    # The user may select another explicit legal Integration. This is a queue
    # choice, not an executed producer, acquired market fact or Source grant.
    request = {
        **common,
        "freeze_relation": frozen["freeze"]["freeze_relation_fingerprint"],
        "preparation_command": str(uuid4()),
        "backtest_command": str(uuid4()),
        "cancel_command": str(uuid4()),
        "qualification_command": str(uuid4()),
        "promotion_command": str(uuid4()),
        "release_manifest_fingerprint": "e" * 64,
        "selected_source": {
            "integration_id": str(uuid4()),
            "integration_revision_fingerprint": "f" * 64,
            "expected_type_id": "binance.spot.market_data",
            "source_id": "binance.spot.market_data.live",
            "environment": "LIVE",
            "instrument_id": "BTCUSDT.BINANCE",
        },
    }

    def run(phase: str, value: dict[str, Any], *, crash: bool = False) -> dict[str, Any]:
        path = root.parent / "use_test_backtest_preparation_request.json"
        path.write_text(json.dumps(value))
        result = subprocess.run(
            [str(binary), "--exact", "actual_command_boundary", "--nocapture"],
            env={
                **os.environ,
                "ONLYALPHA_POSTGRES_DSN": dsn,
                "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
                "ONLYALPHA_FREEZE_TEST_PHASE": "backtest-preparation:" + phase,
                "ONLYALPHA_BACKTEST_PREPARATION_REQUEST": str(path),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == (86 if crash else 0), result.stdout + result.stderr
        import re

        pid = re.search(r"FREEZE_TEST_BACKEND_PID ([0-9]+)", result.stdout)
        assert pid is not None, result.stdout
        wait_no_advisory_locks(dsn, int(pid.group(1)))
        values = [
            json.loads(line.removeprefix("BACKTEST_PREPARATION_VALUE "))
            for line in result.stdout.splitlines()
            if line.startswith("BACKTEST_PREPARATION_VALUE ")
        ]
        assert len(values) == 1, result.stdout
        return values[0]

    def rows() -> list[tuple[Any, ...]]:
        with psycopg.connect(dsn) as db:
            return db.execute(
                "SELECT p.command_id::text,p.preparation_kind,p.accepted_fingerprint,p.accepted_payload,p.state,p.revision,a.command_kind,r.outcome_kind,r.outcome_id "
                "FROM research_preparation p JOIN product_command_admission a USING(command_id) JOIN product_command_receipt r USING(command_id) "
                "WHERE p.preparation_kind='BACKTEST_PREPARATION' ORDER BY p.command_id"
            ).fetchall()

    original = run("accept-no-reply", request, crash=True)
    before = rows()
    assert len(before) == 1
    assert before[0][0] == request["preparation_command"] and before[0][4:] == (
        "ACCEPTED",
        0,
        "PREPARE_BACKTEST",
        "RESEARCH_PREPARATION_OPERATION",
        before[0][2],
    )
    assert json.loads(before[0][3]) == original["accepted"]
    assert original["input"]["research_run_id"] == report["run_id"]
    assert original["input"]["strategy_fingerprint"] == frozen["freeze"]["strategy_fingerprint"]
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        with pytest.raises(psycopg.Error):
            db.execute(
                "UPDATE research_preparation SET preparation_kind='STRATEGY_RESEARCH',revision=revision+1 WHERE command_id=%s",
                (request["preparation_command"],),
            )
        db.rollback()
        with pytest.raises(psycopg.Error):
            db.execute(
                'UPDATE research_preparation SET accepted_payload=(accepted_payload::jsonb || \'{"contract":"ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1"}\'::jsonb)::text,revision=revision+1 WHERE command_id=%s',
                (request["preparation_command"],),
            )
        db.rollback()
    # Replay observes original acceptance before asking for any current file/runtime grant.
    algorithm = Path(common["algorithm_root"])
    absent = algorithm.with_name("use_test_queue_replay_algorithm_unavailable")
    algorithm.rename(absent)
    try:
        replay = run("replay-unavailable", {**request, **original})
        assert replay["replayed"] and replay["view"] == original["view"]
        assert rows() == before
    finally:
        absent.rename(algorithm)
    rejected = run("reject-pins", {**request, "preparation_command": str(uuid4()), "backtest_command": str(uuid4())})
    assert rejected["rejected_pins"] and rows() == before
    parquet = next(path for path in evidence_paths if path.suffix == ".parquet")
    stale = run(
        "stale-evidence",
        {**request, "preparation_command": str(uuid4()), "backtest_command": str(uuid4()), "tamper_path": str(parquet)},
    )
    assert stale["stale_evidence_refused"] and rows() == before
    for phase in ["deferred-guard", "deferred-receipt"]:
        try:
            refused = run(phase, {**request, "preparation_command": str(uuid4()), "backtest_command": str(uuid4())})
            assert refused["deferred_refused"] and rows() == before
        finally:
            with psycopg.connect(dsn) as db:
                db.execute("DROP TRIGGER IF EXISTS use_test_backtest_prepare_fault ON research_preparation")
                db.execute("DROP TRIGGER IF EXISTS use_test_backtest_prepare_fault ON product_command_receipt")
                db.execute("DROP FUNCTION IF EXISTS use_test_backtest_prepare_fault()")
    cancelled = run("cancel", request)
    assert cancelled["cancelled"] and cancelled["view"]["state"] == "CANCELLED"
    with psycopg.connect(dsn) as db:
        assert db.execute(
            "SELECT command_kind FROM product_command_receipt WHERE command_id=%s", (request["cancel_command"],)
        ).fetchone() == ("CANCEL_BACKTEST_PREPARATION",)
        assert db.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
