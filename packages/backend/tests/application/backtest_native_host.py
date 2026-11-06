"""Controlled external inputs through the original ELF and normal Product HTTP.

This is a technical producer/evidence test. Shipping business acceptance still
requires the ordinary Web workflow; these functions create no portable grants.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

import psycopg

from packages.backend.tests.application.support.native_research_market_fixture import ROOT, probe


@contextmanager
def original_host(executable: Path, configuration: dict[str, Any], output: Path) -> Iterator[Any]:
    """Only the selected Runtime ELF starts the unchanged owning Node startup."""
    events: queue.Queue[str] = queue.Queue()
    with (output / "host.log").open("w") as log:
        child = subprocess.Popen(
            [str(executable), "--backtest-native-host"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        assert child.stdin is not None and child.stdout is not None
        child.stdin.write(json.dumps(configuration))
        child.stdin.close()

        def observe() -> None:
            assert child.stdout is not None
            for line in child.stdout:
                events.put(line.rstrip())
            events.put("HOST_EOF")

        reader = threading.Thread(target=observe, name="actual-backtest-host-output")
        reader.start()
        try:
            assert events.get(timeout=30) == "BACKTEST_NATIVE_HOST_READY", (output / "host.log").read_text()
            # Obtain the actual Node's cookie by normal top-level navigation.
            http = build_opener(HTTPCookieProcessor(CookieJar()))
            navigation = Request(
                "http://127.0.0.1:5173/",
                headers={
                    "Accept": "text/html",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Site": "none",
                },
            )
            with http.open(navigation, timeout=10) as response:
                assert response.status == 200 and b"<html" in response.read().lower()
            yield http
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                code = child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
                raise AssertionError("original Node failed to positively drain; Host log retained") from None
            reader.join(timeout=5)
            assert not reader.is_alive()
            assert code == 0, (output / "host.log").read_text()


def request(
    http: Any, path: str, body: dict[str, Any] | None = None, command: str | None = None, *, method: str | None = None
) -> dict[str, Any]:
    headers = {"Origin": "http://127.0.0.1:5173", "Accept": "application/json"}
    if command is not None:
        headers["Idempotency-Key"] = command
    raw = None if body is None else json.dumps(body).encode()
    if raw is not None:
        headers["Content-Type"] = "application/json"
    with http.open(
        Request("http://127.0.0.1:5173" + path, data=raw, headers=headers, method=method), timeout=15
    ) as response:
        assert response.status == 200
        value = response.read(128 * 1024 * 1024 + 1)
        assert len(value) <= 128 * 1024 * 1024
        return json.loads(value)


def observe_until(http: Any, path: str, terminal: set[str], allowed: set[str]) -> dict[str, Any]:
    # Correctness is established by each actual owning response, never a delay.
    # The deadline is an existing technical resource budget, not a state oracle.
    deadline = time.monotonic() + 120
    while True:
        value = request(http, path)
        if value["state"] in terminal:
            return value
        assert value["state"] in allowed, value
        assert time.monotonic() < deadline, value


def qualification(
    binary: Path, dsn: str, root: Path, common: dict[str, Any], frozen: dict[str, Any], output: Path
) -> dict[str, Any]:
    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    value = {
        **common,
        "freeze_relation": frozen["freeze"]["freeze_relation_fingerprint"],
        "preparation_command": str(uuid4()),
        "qualification_command": str(uuid4()),
        "promotion_command": str(uuid4()),
    }
    path = output / "original-qualification-request.json"
    path.write_text(json.dumps(value))
    result = subprocess.run(
        [str(binary), "--exact", "actual_command_boundary", "--nocapture"],
        env={
            **os.environ,
            "ONLYALPHA_POSTGRES_DSN": dsn,
            "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
            "ONLYALPHA_FREEZE_TEST_PHASE": "backtest-preparation:native-qualification",
            "ONLYALPHA_BACKTEST_PREPARATION_REQUEST": str(path),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    (output / "qualification.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    import re

    pid = re.search(r"FREEZE_TEST_BACKEND_PID ([0-9]+)", result.stdout)
    assert pid is not None
    wait_no_advisory_locks(dsn, int(pid.group(1)))
    records = [
        json.loads(line.removeprefix("BACKTEST_PREPARATION_VALUE "))
        for line in result.stdout.splitlines()
        if line.startswith("BACKTEST_PREPARATION_VALUE ")
    ]
    assert len(records) == 1
    return records[0]


def owner_scenario(
    binary: Path,
    dsn: str,
    root: Path,
    configuration: dict[str, Any],
    preparation: str,
    fresh: str | None,
    scenario: str,
    external_files: list[Path],
    output: Path,
) -> None:
    import re

    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    # The immutable Artifact keeps its original formal locator/inode. Execute
    # byte-identical code from another inode so Linux permits the later retained
    # Artifact corruption test after every mathematical child positively joined.
    original = binary.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    selected = binary.stat()
    runner = output / "actual-owner-runner"
    shutil.copyfile(binary, runner)
    runner.chmod(0o500)
    copied = runner.stat()
    assert (copied.st_dev, copied.st_ino) != (selected.st_dev, selected.st_ino)
    assert copied.st_size == selected.st_size == len(original)
    assert runner.read_bytes() == original
    assert hashlib.sha256(runner.read_bytes()).hexdigest() == digest
    path = output / "actual-owner-locators.json"
    path.write_text(
        json.dumps(
            {
                "configuration": configuration,
                "preparation": preparation,
                "fresh": fresh,
                "external_files": [str(p) for p in external_files],
            }
        )
    )
    phases = ["crash-after-publication", "recover-published"] if scenario == "crash-recover" else [scenario]
    for phase in phases:
        result = subprocess.run(
            [str(runner), "--exact", "actual_command_boundary", "--nocapture"],
            env={
                **os.environ,
                "ONLYALPHA_POSTGRES_DSN": dsn,
                "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
                "ONLYALPHA_FREEZE_TEST_PHASE": "backtest-owner:" + phase,
                "ONLYALPHA_BACKTEST_OWNER_REQUEST": str(path),
            },
            capture_output=True,
            text=True,
            timeout=240,
        )
        (output / ("owner-" + phase + ".log")).write_text(result.stdout + result.stderr)
        assert result.returncode == (86 if phase == "crash-after-publication" else 0), result.stdout + result.stderr
        pids = re.findall(r"BACKTEST_OWNER_PID ([0-9]+)", result.stdout)
        assert len(pids) == 1, result.stdout + result.stderr
        wait_no_advisory_locks(dsn, int(pids[0]))
        if phase != "crash-after-publication":
            assert result.stdout.count("BACKTEST_OWNER_SCENARIO_CONFIRMED " + phase) == 1, result.stdout
        retained = binary.stat()
        assert (retained.st_dev, retained.st_ino, retained.st_size) == (
            selected.st_dev,
            selected.st_ino,
            selected.st_size,
        )
        assert binary.read_bytes() == original
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest


def exercise_native_backtest_host(
    binary: Path,
    dsn: str,
    root: Path,
    common: dict[str, Any],
    frozen: dict[str, Any],
    case: dict[str, Any],
    market_probe: Path,
    database: Any,
    output: Path,
    owner_fault: str | None = None,
) -> None:
    from scripts.native_web_e2e import controlled_source_https

    output.mkdir()
    pins = qualification(binary, dsn, root, common, frozen, output)
    assert pins["strategy_fingerprint"] == frozen["freeze"]["strategy_fingerprint"]
    executable = Path(case["selected"])
    selected_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    with controlled_source_https(output) as (ca, external):
        data = root.parent
        source = probe(
            executable,
            database,
            "retained-source-prerequisite",
            fixture_profile="BTC_SPOT_NEXT_OPEN_2025_V1",
            user_data=str(data),
            selected_backend=str(executable),
            selected_backend_sha256=selected_sha,
            source_trust=str(ca),
            integration_id=str(uuid4()),
            create_command=str(uuid4()),
            publish_command=str(uuid4()),
        )
        assert "error" not in source, source
        assert source["controlled_external_input"] is True and source["segment"]["canonical_count"] == 740
        assert (
            source["source"]["integration_revision_fingerprint"]
            == source["segment"]["bar_construction"]["plan"]["integration_revision_fingerprint"]
        )
        assert source["source"]["source_id"] == "binance.spot.market_data.live"
        assert source["selected_backend_sha256"] == selected_sha
        external.update(source["provider_http_fixture"])
        assert len(external["klines"]) == 740
        assert external["klines"][0][0] == 1735861200000  # Jan 2 23:40 UTC
        assert external["klines"][-1][0] == 1735905540000  # Jan 3 11:59 UTC
        (output / "controlled-prior-market-input.json").write_text(json.dumps(source))
        # The owning empty Evidence/Registry operators ran before this case's
        # first business command. Startup must consume those original owners.
        assert (data / "backtest/evidence/.source-cut.lock").is_file()
        assert (data / "backtest/evidence/sha256").is_dir()
        (data / "secrets").mkdir(mode=0o700)
        key = data / "secrets/dev-master-key"
        key.write_bytes(os.urandom(32))
        key.chmod(0o600)
        assets = output / "shipping-web"
        built = subprocess.run(
            ["npm", "run", "build", "--", "--outDir", str(assets), "--emptyOutDir"],
            cwd=ROOT / "packages/frontend",
            capture_output=True,
            text=True,
            timeout=120,
        )
        (output / "shipping-build.log").write_text(built.stdout + built.stderr)
        assert built.returncode == 0, built.stdout + built.stderr
        generation = common["runtime_generation"]
        # Startup reads its configured release's Runtime root. Keep the real
        # Generation directory and all original artifacts in their existing home.
        assert Path(common["runtime_root"]) == data / "runtime"
        configuration = {
            "schema_version": 1,
            "user_data": str(data),
            "schema": str(ROOT / "database/postgres/migrations"),
            "assets": str(assets),
            "algorithms": common["algorithm_root"],
            "algorithm_artifact": common["algorithm_artifact"],
            "source_trust": str(ca),
            "postgres_peer": socket.gethostbyname("postgres") + ":5432",
            "clickhouse_database": database.config.database,
        }
        with original_host(executable, configuration, output) as http:
            preparation, future = str(uuid4()), str(uuid4())
            payload = {
                "schema_version": 2,
                "profile": "BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
                "origin": {"kind": "FROZEN_STRATEGY", **pins},
                "source": {**source["source"], "instrument_id": "BTCUSDT.BINANCE"},
                "release_manifest_fingerprint": hashlib.sha256(
                    (Path(common["algorithm_root"]).parent / "manifest.json").read_bytes()
                ).hexdigest(),
                "expected_active_generation": generation,
                "initialize_fresh_runtime": False,
                "backtest_command_id": future,
            }
            accepted = request(http, "/api/v2/backtest/preparations", payload, preparation)
            assert accepted["command_id"] == preparation and accepted["backtest_command_id"] == future
            assert accepted["run_id"] is None
            ready = observe_until(
                http,
                f"/api/v2/backtest/preparations/commands/{preparation}",
                {"READY"},
                {"ACCEPTED", "RUNNING", "INPUT_PENDING"},
            )
            assert ready["run_id"] is None and ready["backtest_outcome"] == "NOT_SUBMITTED"
            with psycopg.connect(dsn) as db:
                assert db.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
                assert db.execute(
                    "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (future,)
                ).fetchone() == (0,)
            if owner_fault is not None:
                fresh = None
                if owner_fault == "windows":
                    fresh, fresh_future = str(uuid4()), str(uuid4())
                    other = {**payload, "backtest_command_id": fresh_future}
                    request(http, "/api/v2/backtest/preparations", other, fresh)
                    unsubmitted = observe_until(
                        http,
                        f"/api/v2/backtest/preparations/commands/{fresh}",
                        {"READY"},
                        {"ACCEPTED", "RUNNING", "INPUT_PENDING"},
                    )
                    assert unsubmitted["run_id"] is None and unsubmitted["backtest_outcome"] == "NOT_SUBMITTED"
                with psycopg.connect(dsn) as db:
                    retained = json.loads(
                        db.execute(
                            "SELECT outputs_payload FROM research_preparation WHERE command_id=%s", (preparation,)
                        ).fetchone()[0]
                    )["ready"]
                snapshot = retained["input_sources"]["sources"][0]["snapshot"]
                relation = pins["freeze_relation_fingerprint"]
                external_files = [
                    executable,
                    Path(common["algorithm_root"]) / "lib/python3.12/site-packages/onlyalpha/__init__.py",
                    root / "datasets/sha256" / snapshot[:2] / snapshot / "manifest.json",
                    root / "strategy/freeze-relations/sha256" / relation[:2] / relation / "manifest.json",
                ]
                assert len(external_files) == 4 and all(path.is_file() for path in external_files)
            else:
                submitted = request(
                    http,
                    f"/api/v2/backtest/preparations/{preparation}/submit",
                    {
                        "schema_version": 1,
                        "preparation_command_id": preparation,
                        "preparation_fingerprint": ready["preparation_fingerprint"],
                    },
                    future,
                )
                assert submitted["state"] == "ACCEPTED" and submitted["backtest_command_id"] == future
                run = submitted["run_id"]
                completed = observe_until(http, f"/api/v2/backtest/runs/{run}", {"COMPLETED"}, {"QUEUED", "RUNNING"})
                assert completed["preparation_command_id"] == preparation
                result = request(http, f"/api/v2/backtest/runs/{run}/result")
                assert result["run_id"] == run and result["strategy_fingerprint"] == pins["strategy_fingerprint"]
                assert result["state"] == "COMPLETED" and len(result["curve"]) == 720
                assert (
                    result["sample"]["start_at"] == "2025-01-03T00:00:00Z"
                    and result["sample"]["end_at"] == "2025-01-03T12:00:00Z"
                )
                assert Decimal(result["sample"]["quantity"]) == Decimal(".01")
                metrics = result["metrics"]
                assert (metrics["fill_count"], metrics["roundtrip_count"]) == (2, 1)
                for key, expected in [
                    ("initial_equity", "10000"),
                    ("final_equity", "9994.60119940"),
                    ("fees", "1.99900060"),
                    ("unrealized_pnl", "0"),
                ]:
                    assert Decimal(metrics[key]) == Decimal(expected)
                assert [Decimal(t["price"]) for t in result["trades"]] == [
                    Decimal("100120.020000"),
                    Decimal("99780.040000"),
                ]
                assert result["trades"][0]["time_ns"] == "1735862460000000000"  # 00:01 next open
                assert result["trades"][1]["time_ns"] == "1735862520000000000"  # 00:02 next open
                assert Decimal(result["baseline"]["final_equity"]) == Decimal("9998.7998")
                trace = request(http, f"/api/v2/backtest/runs/{run}/evidence/artifacts/replay-trace.json")
                assert trace["schema_version"] == 2 and trace["kind"] == "RUNTIME_ENCODED_REPLAY_TRACE"
                assert trace["binding"]["schema_version"] == 2 and trace["binding"]["work_id"] == run
                bars = [value["bar"] for value in trace["inputs"]["records"]]
                assert len(bars) == 740

                def instant(value: str) -> datetime:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

                assert instant(bars[0]["bar_start"]) == datetime(2025, 1, 2, 23, 40, tzinfo=UTC)
                assert instant(bars[-1]["bar_start"]) == datetime(2025, 1, 3, 11, 59, tzinfo=UTC)
                assert instant(bars[-1]["ts_event"]) == datetime(2025, 1, 3, 12, tzinfo=UTC)
                assert all(instant(bar["bar_start"]) < datetime(2025, 1, 3, 12, tzinfo=UTC) for bar in bars)
                assert all(instant(bar["ts_event"]) < datetime(2025, 1, 5, tzinfo=UTC) for bar in bars)
                evidence = request(http, f"/api/v2/backtest/runs/{run}/evidence")
                assert evidence["manifest"]["schema_version"] == 3
                assert evidence["manifest"]["backtest_run_id"] == run
                runtime = request(http, f"/api/v2/backtest/runs/{run}/evidence/artifacts/runtime.json")
                assert runtime["schema_version"] == 2 and runtime["contract"] == "ONLYALPHA_NATIVE_BACKTEST_PRODUCER_V2"
                assert runtime["executor_manifest"]["artifact_sha256"] == selected_sha
                journal = data / "backtest/runtime" / run / "runtime.sqlite3"
                before = (journal.stat().st_ino, hashlib.sha256(journal.read_bytes()).hexdigest())
                original = runtime["ready"]["preparation"]
                scope = {
                    "schema_version": 1,
                    "contract": "ONLYALPHA_BACKTEST_TERMINAL_READ_V1",
                    "journal_root": str(journal.parent),
                    "specification": {
                        "work_id": run,
                        "configuration": original["settings"]["execution"],
                        "kernel_artifact": selected_sha,
                        "driver_artifact": selected_sha,
                        "initial_ns": original["initial_ns"],
                    },
                    "inputs": runtime["ready"]["input_sources"],
                }
                # Actual original ELF, empty operational environment: the private
                # read mode cannot bootstrap a Node/SDK or recover/ack its source.
                reread = subprocess.run(
                    [str(executable), "--read-native-backtest-terminal"],
                    input=json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    text=True,
                    capture_output=True,
                    env={},
                    timeout=120,
                )
                assert reread.returncode == 0, reread.stderr
                historical = json.loads(reread.stdout)
                assert historical["reader_artifact"] == selected_sha and historical["trace"] == trace
                assert historical["result"]["result_fingerprint"] == result["result_fingerprint"]
                assert (journal.stat().st_ino, hashlib.sha256(journal.read_bytes()).hexdigest()) == before
                assert all(
                    not journal.with_name(journal.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
                )
                observed = request(http, f"/api/v2/backtest/runs/{run}/evidence/artifacts/observation.json")
                assert observed["sample_bar_count"] == 720
                with psycopg.connect(dsn) as db:
                    rows = db.execute(
                        "SELECT state,specification_schema_version,admission_resolution_schema_version,result_fingerprint,determinism_fingerprint FROM backtest_run WHERE run_id=%s",
                        (run,),
                    ).fetchall()
                    assert rows == [
                        ("COMPLETED", 3, 2, result["result_fingerprint"], result["determinism_fingerprint"])
                    ]
                    assert db.execute("SELECT state FROM backtest_run_attempt WHERE run_id=%s", (run,)).fetchall() == [
                        ("SUCCEEDED",)
                    ]
                    outputs = json.loads(
                        db.execute(
                            "SELECT outputs_payload FROM research_preparation WHERE command_id=%s", (preparation,)
                        ).fetchone()[0]
                    )
                    actual = outputs["ready"]["rules_response"]
                    assert hashlib.sha256(actual["body"].encode()).hexdigest() == actual["body_sha256"]
                    assert (
                        json.loads(actual["body"])["symbols"][0]
                        == actual["snapshot"]["raw_symbol"]
                        == external["exchange_info"]["symbols"][0]
                    )
                    assert outputs["ready"]["backtest_binding"]["executor_artifact_sha256"] == selected_sha
                # Current eligibility may be withdrawn after original acceptance.
                # Only the ordinary Integration lifecycle command does that here.
                request(
                    http,
                    f"/api/v2/integrations/{source['source']['integration_id']}/lifecycle",
                    {"schema_version": 1, "expected_lifecycle_state": "ACTIVE", "lifecycle_state": "DISABLED"},
                    str(uuid4()),
                    method="PUT",
                )
                history = request(http, f"/api/v2/backtest/preparations/commands/{preparation}")
                assert history["backtest_outcome"] == "ACCEPTED" and history["run_id"] == run
                assert history["command_id"] == preparation and history["backtest_command_id"] == future
                again = request(http, f"/api/v2/backtest/runs/{run}")
                assert again["state"] == "COMPLETED" and again["report_status"]["state"] == "VERIFIED"
                assert request(http, f"/api/v2/backtest/runs/{run}/result") == result
                (output / "actual-native-result.json").write_text(json.dumps(result))
        if owner_fault is not None:
            # original_host has positively drained its own Running/Authority
            # before the next process opens the same physical owning resource.
            owner_scenario(binary, dsn, root, configuration, preparation, fresh, owner_fault, external_files, output)
        occurrences = [json.loads(line) for line in (output / "controlled-source-https.jsonl").read_text().splitlines()]
        assert any(row.get("path") == "/api/v3/exchangeInfo" and row.get("status") == 200 for row in occurrences), (
            occurrences
        )
