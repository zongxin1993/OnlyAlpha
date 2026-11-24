from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
from contextlib import contextmanager
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, BinaryIO
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

import psycopg

from packages.backend.tests.application.backtest_native_host import (
    assert_query_error,
    backtest_acceptance,
    cancel_receipts,
    original_host,
    prepare_comparison,
    publication_identity,
    read_backtest_publication,
    request,
    run_comparison,
    submit_comparison,
)
from packages.backend.tests.application.support.native_research_market_fixture import ROOT
from packages.backend.tests.application.test_strategy_research_evidence import http_json

ORIGIN = "http://127.0.0.1:5173"
SESSION = "/api/v2/human/session"
RUNS = "/api/v2/backtest/runs"


def assert_single_human_session(http: Any) -> None:
    expected = {"subject_id": "local-developer", "can_logout": False}
    assert request(http, SESSION) == expected
    status, _ = http_json(http, "DELETE", SESSION, None, {})
    assert status == 403
    assert request(http, SESSION) == expected


def login(subject: str, credential: str, jar: CookieJar) -> Any:
    http = build_opener(HTTPCookieProcessor(jar))
    expected = {"subject_id": subject, "can_logout": True}
    status, identity = http_json(http, "POST", SESSION, None, {"Authorization": "Bearer " + credential})
    assert status == 200 and identity == expected
    assert request(http, SESSION) == expected
    return http


def private_json(directory: Path, value: Any) -> Path:
    with NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
        json.dump(value, stream)
        return Path(stream.name)


def check_browser(directory: Path, fixture: Path) -> dict[str, int]:
    browser_env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "PLAYWRIGHT_BROWSERS_PATH",
            "PLAYWRIGHT_EXECUTABLE_PATH",
        )
        if key in os.environ
    }
    run = subprocess.run(
        [
            "npm",
            "exec",
            "--",
            "playwright",
            "test",
            "e2e/backtest-owner-isolation.spec.ts",
            "--workers=1",
            "--retries=0",
            "--trace=off",
            "--reporter=json",
        ],
        cwd=ROOT / "packages/frontend",
        env={
            **browser_env,
            "ONLYALPHA_BROWSER_HUMAN_FIXTURE": str(fixture),
            "PLAYWRIGHT_BASE_URL": ORIGIN,
            "PLAYWRIGHT_OUTPUT_DIR": str(directory / "browser"),
        },
        capture_output=True,
    )
    fixture.unlink()
    # 浏览器错误可能包含键盘输入，仅提取用例行号和计数。
    report = json.loads(run.stdout)
    counts = {key: report["stats"][key] for key in ("expected", "skipped", "unexpected", "flaky")}
    if run.returncode != 0 or counts != {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0}:
        locations = sorted(set(re.findall(r"backtest-owner-isolation\.spec\.ts:(\d+:\d+)", json.dumps(report))))
        raise AssertionError(f"Playwright exit={run.returncode} counts={counts} spec_locations={locations}")
    return counts


def prepared_market(dsn: str, command: str, owner: str, source: dict[str, Any]) -> dict[str, Any]:
    with psycopg.connect(dsn) as db:
        row = db.execute(
            "SELECT outputs_payload::jsonb->'ready' FROM public.research_preparation WHERE command_id=%s AND owner=%s",
            (command, owner),
        ).fetchone()
    assert row is not None
    ready = row[0]
    selection = ready["source_selection"]
    assert ready["dataset_materialization_id"] and selection["preparation_command_id"] == command
    assert selection["source"] == source
    acquisition = selection["acquisition"]
    assert acquisition["status"] == "COMPLETE"
    assert (acquisition["start_ns"], acquisition["end_ns"]) == ("1735861200000000000", "1735905600000000000")
    assert acquisition["revision_fingerprint"] == selection["revision"]["fingerprint"]
    assert acquisition["seal_id"] == selection["seal"]["seal_id"]
    return {
        "acquisition_id": acquisition["acquisition_id"],
        "scope": selection["scope"],
        "revision": selection["revision"],
        "seal": selection["seal"],
    }


@contextmanager
def host_with_worker_gates(executable: Path, configuration: dict[str, Any], output: Path, policy: Path):
    # sockaddr_un 的路径长度有限，使用短路径和仅本用户可进入的临时目录。
    with TemporaryDirectory(dir="/tmp", prefix="oa-gate-") as temporary, socket.socket(socket.AF_UNIX) as listener:
        path = str(Path(temporary) / "worker.sock")
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(30)
        with original_host(
            executable, {**configuration, "worker_gate_socket": path}, output, human_credentials_file=policy
        ) as http:
            connection, _ = listener.accept()
            with connection, connection.makefile("rwb", buffering=0) as gate:
                connection.settimeout(120)
                yield http, gate


def logout_and_check_old_cookie(http: Any, jar: CookieJar, run: str) -> None:
    # DELETE 清除调用方的 Cookie，复制后调用可独立检查原 Cookie 的服务端状态。
    logout_jar = CookieJar()
    for cookie in jar:
        logout_jar.set_cookie(cookie)
    logout = build_opener(HTTPCookieProcessor(logout_jar))
    with logout.open(Request(ORIGIN + SESSION, method="DELETE", headers={"Origin": ORIGIN}), timeout=15) as response:
        assert response.status == 204 and response.read() == b""
    assert http_json(http, "GET", SESSION, None, {})[0] == 401
    assert http_json(http, "GET", f"{RUNS}/{run}", None, {})[0] == 401


def run_after_logout(
    gate: BinaryIO,
    dsn: str,
    subject: str,
    owner: Any,
    jar: CookieJar,
    preparation: str,
    run: str,
    other: Any,
    other_run: str,
    to_cancel: tuple[str, str],
) -> dict[str, Any]:
    gate.write((run + "\n").encode("ascii"))
    assert gate.readline(64) == b"armed\n"
    command = submit_comparison(owner, preparation, run)
    assert gate.readline(64) == b"before_claim\n"
    accepted = backtest_acceptance(dsn, run, command, owner=subject)
    queued, attempts, publications, members = publication_identity(dsn, run)
    assert queued[0] == "QUEUED" and not (attempts or publications or members)
    own = request(owner, f"{RUNS}/{run}")
    assert own["state"] == "QUEUED" and own["worker_observation"]["state"] == "RUNNING"
    assert own["worker_observation"]["run_id"] == run
    (visible,) = request(other, RUNS)["items"]
    assert visible["run_id"] == other_run and "worker_observation" not in visible
    cancel_preparation, cancel_run = to_cancel
    submit_comparison(other, cancel_preparation, cancel_run)
    logout_and_check_old_cookie(owner, jar, run)
    gate.write(b"release\n")
    assert gate.readline(64) == b"after_first_step\n"
    running, attempts, publications, members = publication_identity(dsn, run)
    ((attempt_id, number, state, fence, worker),) = attempts
    assert running[0] == "RUNNING" and (number, state, fence) == (1, "ACTIVE", 1)
    assert not (publications or members)
    assert http_json(owner, "GET", f"{RUNS}/{run}", None, {})[0] == 401

    items = request(other, RUNS)["items"]
    assert {item["run_id"] for item in items} == {other_run, cancel_run}
    assert all("worker_observation" not in item for item in items)
    detail = request(other, f"{RUNS}/{cancel_run}")
    assert detail["run_id"] == cancel_run and detail["state"] == "QUEUED" and "worker_observation" not in detail
    cancel = str(uuid4())
    cancelled = request(other, f"{RUNS}/{cancel_run}/cancellation", {"schema_version": 1, "run_id": cancel_run}, cancel)
    assert cancelled["run_id"] == cancel_run and cancelled["state"] == "CANCELLED"
    assert "worker_observation" not in cancelled and set(cancel_receipts(dsn, cancel_run)) == {cancel}
    gate.write(b"release\n")
    assert gate.readline(64) == b"after_publish\n"
    completed, attempts, publications, members = publication_identity(dsn, run)
    ((winner, publication, _, published_number, published_fence, published_worker, published_binding),) = publications
    assert completed[0] == "COMPLETED" and completed[3:6] == (publication,) * 3
    assert attempts == [(attempt_id, number, "SUCCEEDED", fence, worker)]
    assert (winner, published_number, published_fence, published_worker) == (attempt_id, number, fence, worker)
    assert published_binding == accepted[1]
    assert [row[0] for row in members] == ["causal_evidence", "close_curve", "economic_result", "execution_facts"]
    assert backtest_acceptance(dsn, run, command, owner=subject) == accepted
    assert json.loads(members[0][3])["body"]["binding"] == json.loads(accepted[2])
    return {
        "run_id": run,
        "command": command,
        "attempt_id": str(attempt_id),
        "binding": published_binding,
        "publication": publication,
        "before_claim": queued[0],
        "after_first_step": running[0],
        "after_publish": completed[0],
        "cancelled_run": cancel_run,
        "cancel_command": cancel,
        "owner_observed_run": own["worker_observation"]["run_id"],
        "other_list": [item["run_id"] for item in items],
        "other_detail": detail["run_id"],
        "other_cancellation": cancelled["state"],
    }


def exercise_human_owners(
    executable: Path,
    configuration: dict[str, Any],
    output: Path,
    payload: dict[str, Any],
    pins: dict[str, Any],
    selected_sha: str,
    dsn: str,
    preflight: str,
) -> None:
    subjects = ("backtest-owner-a", "backtest-owner-b")
    credentials = {subject: os.urandom(32).hex() for subject in subjects}
    source = payload["source"]
    selection = {field: source[field] for field in ("integration_id", "expected_type_id", "source_id", "environment")}
    selection["revision_fingerprint"] = source["integration_revision_fingerprint"]
    market = prepared_market(dsn, preflight, "local-developer", source)
    policies = [
        {
            "subject_id": subject,
            "credential_sha256": hashlib.sha256(credentials[subject].encode("ascii")).hexdigest(),
            "closed_history": [selection],
            "frozen_strategy_fingerprints": [pins["strategy_fingerprint"]],
        }
        for subject in subjects
    ]
    with TemporaryDirectory(dir=Path(configuration["user_data"]) / "secrets") as temporary:
        directory = Path(temporary)
        policy = private_json(directory, policies)
        with host_with_worker_gates(executable, configuration, output, policy) as (anonymous, gate):
            assert http_json(anonymous, "GET", SESSION, None, {})[0] == 401
            jars = {subject: CookieJar() for subject in subjects}
            sessions = {subject: login(subject, credentials[subject], jars[subject]) for subject in subjects}
            a, b = subjects
            records = {}
            for subject in subjects:
                preparation, run_id = prepare_comparison(sessions[subject], payload)
                assert prepared_market(dsn, preparation, subject, source) == market
                records[subject] = {"preparation": preparation, "run_id": run_id}
            run_comparison(sessions[a], records[a]["preparation"], records[a]["run_id"])
            to_cancel = prepare_comparison(sessions[a], payload)
            assert prepared_market(dsn, to_cancel[0], a, source) == market
            old_b = sessions[b]
            execution = run_after_logout(
                gate,
                dsn,
                b,
                old_b,
                jars[b],
                records[b]["preparation"],
                records[b]["run_id"],
                sessions[a],
                records[a]["run_id"],
                to_cancel,
            )
            sessions[b] = login(b, credentials[b], CookieJar())
            assert http_json(old_b, "GET", f"{RUNS}/{records[b]['run_id']}", None, {})[0] == 401
            for subject, record in records.items():
                preparation, run_id = record["preparation"], record["run_id"]
                history = request(sessions[subject], f"/api/v2/backtest/preparations/commands/{preparation}")
                command = history["backtest_command_id"]
                backtest_acceptance(dsn, run_id, command, owner=subject)
                _, evidence, _ = read_backtest_publication(sessions[subject], run_id, preparation, pins, selected_sha)
                record.update(command=command, publication=evidence["publication_fingerprint"])
            assert all(records[b][key] == execution[key] for key in ("run_id", "command", "publication"))
            for field in ("preparation", "command", "run_id"):
                assert records[a][field] != records[b][field]
            for subject, foreign in ((a, b), (b, a)):
                items = request(sessions[subject], RUNS)["items"]
                expected_runs = {records[a]["run_id"], to_cancel[1]} if subject == a else {records[b]["run_id"]}
                assert {item["run_id"] for item in items} == expected_runs and len(items) == len(expected_runs)
                path = f"{RUNS}/{records[foreign]['run_id']}"
                for suffix in ("", "/result", "/evidence", "/evidence/artifacts/causal_evidence"):
                    assert_query_error(sessions[subject], path + suffix, 404, "BACKTEST_RUN_NOT_FOUND")
            a_run, b_run = (f"{RUNS}/{records[subject]['run_id']}" for subject in subjects)
            assert http_json(anonymous, "GET", a_run, None, {})[0] == 401

            logout_and_check_old_cookie(sessions[a], jars[a], records[a]["run_id"])
            assert request(sessions[b], SESSION) == {"subject_id": b, "can_logout": True}
            assert request(sessions[b], b_run)["state"] == "COMPLETED"
            renewed = login(a, credentials[a], CookieJar())
            assert request(renewed, a_run)["state"] == "COMPLETED"
            assert http_json(sessions[a], "GET", a_run, None, {})[0] == 401

            fixture = private_json(
                directory,
                {
                    "owners": [
                        {"subject_id": subject, "credential": credentials[subject], "run_id": records[subject]["run_id"]}
                        for subject in subjects
                    ]
                },
            )
            browser_counts = check_browser(directory, fixture)
            receipt = {
                "owners": records,
                "execution_after_logout": execution,
                "market_acquisition_id": market["acquisition_id"],
                "frozen_strategy": pins["strategy_fingerprint"],
                "cross_owner_status": 404,
                "anonymous_status": 401,
                "revoked_status": 401,
                "browser": browser_counts,
            }
            print("BACKTEST_HUMAN_OWNER_ISOLATION " + json.dumps(receipt, sort_keys=True), flush=True)
