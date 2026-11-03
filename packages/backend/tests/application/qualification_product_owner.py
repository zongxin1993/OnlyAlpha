"""Qualification Product original-command seam, using existing real completed science."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg


def exercise_qualification_product(
    binary: Path, dsn: str, root: Path, common: dict[str, Any], frozen: dict[str, Any]
) -> None:
    from tests.support.postgres_link import wait_no_advisory_locks

    request = {
        **common,
        "strategy_fingerprint": frozen["freeze"]["strategy_fingerprint"],
        "freeze_relation": frozen["freeze"]["freeze_relation_fingerprint"],
        "qualification_command": str(uuid4()),
        "promotion_command": str(uuid4()),
        "at": "2026-11-02T00:00:00.123456Z",
    }

    def run(phase: str, *, crash: bool = False, at: str | None = None) -> dict[str, Any] | None:
        path = root.parent / "use_test_qualification_product_request.json"
        path.write_text(json.dumps({**request, **({"at": at} if at else {})}))
        result = subprocess.run(
            [str(binary), "--exact", "actual_command_boundary", "--nocapture"],
            env={
                **os.environ,
                "ONLYALPHA_POSTGRES_DSN": dsn,
                "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
                "ONLYALPHA_FREEZE_TEST_PHASE": "qualification-product:" + phase,
                "ONLYALPHA_QUALIFICATION_PRODUCT_REQUEST": str(path),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == (86 if crash else 0), result.stdout + result.stderr
        pid = re.search(r"FREEZE_TEST_BACKEND_PID ([0-9]+)", result.stdout)
        assert pid is not None, result.stdout
        wait_no_advisory_locks(dsn, int(pid.group(1)))
        if crash:
            return None
        values = [
            json.loads(line.removeprefix("QUALIFICATION_PRODUCT_VALUE "))
            for line in result.stdout.splitlines()
            if line.startswith("QUALIFICATION_PRODUCT_VALUE ")
        ]
        assert len(values) == 1, result.stdout
        return values[0]

    def rows() -> dict[str, list[tuple[Any, ...]]]:
        with psycopg.connect(dsn) as db:
            return {
                "qualification": db.execute(
                    "SELECT * FROM qualification_command_admission WHERE command_id=%s",
                    (request["qualification_command"],),
                ).fetchall(),
                "promotion": db.execute(
                    "SELECT * FROM strategy_promotion_record ORDER BY promotion_record_fingerprint"
                ).fetchall(),
                "commands": db.execute(
                    "SELECT command_id::text,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at FROM product_command_receipt WHERE command_id IN (%s,%s) ORDER BY command_id",
                    (request["qualification_command"], request["promotion_command"]),
                ).fetchall(),
            }

    run("qualification-stop:prepared", crash=True)
    before = rows()
    files = {str(p): p.read_bytes() for p in (root / "strategy/qualification-decisions").rglob("manifest.json")}
    observed = run("observe")
    assert observed is not None and observed["state"] == "PREPARED"
    assert observed["decision_fingerprint"] is None and observed["completed_at"] is None
    assert (
        rows() == before
        and {str(p): p.read_bytes() for p in (root / "strategy/qualification-decisions").rglob("manifest.json")}
        == files
    )
    prepared_at = observed["prepared_at"]
    complete = run("resume", at="2026-11-02T00:00:20.654321Z")
    assert complete is not None
    assert complete["state"] == "COMPLETED" and complete["prepared_at"] == prepared_at
    assert complete["decision_fingerprint"] and complete["completed_at"] == "2026-11-02T00:00:20.654321Z"
    after = rows()
    assert run("resume", at="2026-11-02T00:00:40Z") == complete
    assert rows() == after
    # Current installed SDK is irrelevant to observing the original durable command.
    algorithm = Path(common["algorithm_root"])
    hidden = algorithm.with_name("use_test_qualification_sdk_unavailable")
    algorithm.rename(hidden)
    try:
        assert run("observe") == complete and rows() == after
    finally:
        hidden.rename(algorithm)
    run("promotion-stop", crash=True, at="2026-11-02T00:00:30.123456Z")
    promoted = run("promotion-observe")
    assert promoted is not None and promoted["state"] == "COMPLETED"
    assert promoted["record"]["schema_version"] == 2 and promoted["record"]["to_stage"] == "BACKTEST"
    assert promoted["record"]["recorded_at"] == "2026-11-02T00:00:30.123456+00:00"
    before = rows()
    assert run("promotion-resume", at="2026-11-02T00:00:55Z") == promoted
    assert rows() == before
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM qualification_command_admission").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM strategy_promotion_record").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
