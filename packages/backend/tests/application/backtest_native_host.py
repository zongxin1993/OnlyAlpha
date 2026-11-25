"""Controlled external inputs through the original ELF and normal Product HTTP.

This is a technical producer/evidence test. Shipping business acceptance still
requires the ordinary Web workflow; these functions create no portable grants.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import datetime
from decimal import Decimal
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import UUID, uuid4

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from psycopg import sql

from packages.backend.tests.application.support.backtest_publication_comparison import assert_equivalent_publications
from packages.backend.tests.application.support.native_research_market_fixture import ROOT, MarketStorageInputs, probe

# 单调计时标记：只记录真实发生的阶段边界，不把任何实际工作移出计时窗口，也不改变任何
# 既有预算（Host 就绪 30s、观测循环 120s、npm build 120s、qualification 120s 全部保留）。
# 原始里程碑一律以「纳秒绝对时刻」存放，键名以 `_ns` 结尾；对外的 `_us` 字段只在
# timing_report() 这个唯一换算点由纳秒除以 1000 得到。绝不把纳秒数值写进 `_us` 字段
# （那会虚报 1000 倍），也不为没有真实发生的里程碑补 0：未达到或被整案预算截断就是键缺失，
# 缺失本身即「未到达/未采集」的证据。互斥耗时由相邻绝对时刻相减；包含关系由键名
# `*-begin`/`*-end` 配对显式表达，两者不得混算。
_ORIGIN_NS = time.monotonic_ns()
_STAGES_NS: dict[str, int] = {}
# 追加式落盘目标：外层整案预算直接终止 pytest 时，尚未呈现的 stdout 可能来不及看到，
# 逐行 flush 的追加文件保证已经真实发生的边界仍能被读出来。
_STAGE_SINK: list[Path] = []
# 当前链路标签只写在文本字段里，不混进任何耗时数值。
_STAGE_CASE = "unlabelled"
# 链路代次：每条业务链路一个编号。上一条链路的汇总快照按代次落盘，保证「一条链路最多
# 一条汇总」，不会因为 reset_stages 与 set_stage_sink 的先后顺序不同而重复或错档。
_STAGE_GENERATION = [0]
_SNAPSHOT_GENERATION = [-1]
# 生命周期标记按 Host 实例编号：这张绝对时刻表是进程级的，同一个用例里如果出现第二个
# Host 实例，没有序号的 spawn/ready 会被重复标记保护直接拦下。当前
# exercise_native_backtest_host 只有一个 original_host 调用点（第 473 行），编号的作用是
# 让任何再增加 Host 实例的路径都不会撞名，而不是声称现在已经有两个 Host。
_HOST_SERIAL = itertools.count(1)


def milestone(name: str) -> None:
    """记录一个确实已经发生的阶段边界，与 Host 生命周期共用同一张绝对时刻表。"""
    key = f"{name}_ns"
    if key in _STAGES_NS:
        raise RuntimeError(f"duplicate timing marker: {key} already in {_STAGES_NS}")
    value = time.monotonic_ns() - _ORIGIN_NS
    _STAGES_NS[key] = value
    if _STAGE_SINK:
        with _STAGE_SINK[0].open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"kind": "marker", "case": _STAGE_CASE, "name": name, "value_us": (value + 500) // 1000})
                + "\n"
            )


# 业务大阶段边界与 Host 生命周期里程碑共用同一张表，避免两套计时互相混算。
stage = milestone


def timing_report() -> str:
    """唯一换算点：纳秒 → 微秒（四舍五入），键名后缀换成 `_us`。"""
    return json.dumps(
        {f"{key.removesuffix('_ns')}_us": (value + 500) // 1000 for key, value in sorted(_STAGES_NS.items())},
        sort_keys=True,
    )


def dump_stages(label: str) -> None:
    """把当前绝对时刻表原样打出来；未达到的键保持缺失，不补 0。"""
    report = timing_report()
    print(f"[native-stage-timing] label={label} {report}", flush=True)
    if _STAGE_SINK:
        with _STAGE_SINK[0].open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"kind": "report", "case": _STAGE_CASE, "label": label, "stages_us": json.loads(report)})
                + "\n"
            )


def _write_superseded() -> None:
    """把上一条链路的绝对时刻表原样落盘，每条链路最多一次。

    上一用例的临时目录可能已经不存在：快照仍然完整打印在 stdout，
    不能因为诊断文件写不进去就把后续业务用例打成失败。
    """
    if not _STAGES_NS or _SNAPSHOT_GENERATION[0] == _STAGE_GENERATION[0]:
        return
    try:
        dump_stages(f"superseded:{_STAGE_CASE}")
    except OSError as error:
        print(
            f"[native-stage-timing] superseded-snapshot-write-failed case={_STAGE_CASE} "
            f"error={type(error).__name__}:{error} snapshot_still_on_stdout=true",
            flush=True,
        )
    _SNAPSHOT_GENERATION[0] = _STAGE_GENERATION[0]


def set_stage_sink(path: Path) -> None:
    """指定追加式计时文件；同一文件可被多条链路共用，每行自带 case 标签。

    切换文件时如果表里还留着上一条链路的边界，先把汇总落到切换前的那个文件：
    汇总因此始终属于它自己的链路，不会因为调用方把 reset_stages 与 set_stage_sink
    的先后写反而混进新链路的文件。同一条链路换文件后继续记录的边界仍按行写入新文件，
    但不再重复生成上一条链路的汇总。
    """
    current = _STAGE_SINK[0] if _STAGE_SINK else None
    if path != current:
        _write_superseded()
    _STAGE_SINK.clear()
    _STAGE_SINK.append(path)


def reset_stages(case_label: str) -> None:
    """开启一条新的业务链路计时：先落盘上一链路快照，再清空绝对时刻表。

    清空后表里只剩本次链路真实记录的边界；标签只写在快照行里，不混进数值字段。
    推荐顺序仍是 reset_stages(新标签) → set_stage_sink(新文件) → stage("case-begin")，
    但快照按链路代次落盘，两种先后都不会串档。
    """
    global _STAGE_CASE
    _write_superseded()
    _STAGES_NS.clear()
    _STAGE_GENERATION[0] += 1
    _STAGE_CASE = case_label
    print(f"[native-stage-timing] reset case={case_label} stages_cleared=true", flush=True)


@contextmanager
def original_host(
    executable: Path, configuration: dict[str, Any], output: Path, *, diagnostics: Path | None = None,
    human_credentials_file: Path | None = None,
) -> Iterator[Any]:
    """Only the selected Runtime ELF starts the unchanged owning Node startup."""
    events: queue.Queue[str] = queue.Queue()
    serial = next(_HOST_SERIAL)
    # 一条用例可能先后起多个 Host（如 PG 发布模式：Freeze 专用 Host 排空后才起正式 Host），
    # 各自的 stderr 日志按 serial 分文件，后起的 Host 不得覆盖前一个 Host 的现场。
    log_path = output / f"host{serial}.log"
    env = os.environ.copy()
    env.pop("ONLYALPHA_HUMAN_CREDENTIALS_FILE", None)
    if human_credentials_file is not None:
        env["ONLYALPHA_HUMAN_CREDENTIALS_FILE"] = str(human_credentials_file)
    if diagnostics is not None:
        env["ONLYALPHA_DIAGNOSTICS_PATH"] = str(diagnostics)
    mode = "--backtest-native-host-with-worker-gates" if "worker_gate_socket" in configuration else "--backtest-native-host"
    with log_path.open("w") as log:
        child = subprocess.Popen(
            [str(executable), mode],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        stage(f"host{serial}-spawn")
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
            try:
                first_event = events.get(timeout=30)
            except queue.Empty:
                stage(f"host{serial}-ready-timeout")
                print(f"[native-host-timing] {timing_report()}", flush=True)
                raise AssertionError(
                    f"BACKTEST_NATIVE_HOST_READY missing within 30s; "
                    f"stages={_STAGES_NS}; host log tail:\n{log_path.read_text()[-4000:]}"
                ) from None
            stage(f"host{serial}-first-event")
            assert first_event == "BACKTEST_NATIVE_HOST_READY", log_path.read_text()
            stage(f"host{serial}-ready")
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
            stage(f"host{serial}-navigation")
            yield http
        finally:
            stage(f"host{serial}-terminate")
            if child.poll() is None:
                child.terminate()
            try:
                code = child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
                stage(f"host{serial}-kill")
                print(f"[native-host-timing] {timing_report()}", flush=True)
                raise AssertionError("original Node failed to positively drain; Host log retained") from None
            stage(f"host{serial}-drained")
            print(f"[native-host-timing] {timing_report()} code={code}", flush=True)
            reader.join(timeout=5)
            assert not reader.is_alive()
            assert code == 0, log_path.read_text()


def response_bytes(
    http: Any, path: str, body: dict[str, Any] | None = None, command: str | None = None, *, method: str | None = None
) -> tuple[bytes, str]:
    headers = {"Origin": "http://127.0.0.1:5173", "Accept": "application/json, application/octet-stream"}
    if command is not None:
        headers["Idempotency-Key"] = command
    raw = None if body is None else json.dumps(body).encode()
    if raw is not None:
        headers["Content-Type"] = "application/json"
    try:
        with http.open(
            Request("http://127.0.0.1:5173" + path, data=raw, headers=headers, method=method), timeout=15
        ) as response:
            assert response.status == 200
            value = response.read(128 * 1024 * 1024 + 1)
            assert len(value) <= 128 * 1024 * 1024
            return value, response.headers.get_content_type()
    except HTTPError as error:
        with error:
            raise AssertionError(f"{path} returned HTTP {error.code}: {error.read(4096)!r}") from error


def request(
    http: Any, path: str, body: dict[str, Any] | None = None, command: str | None = None, *, method: str | None = None
) -> dict[str, Any]:
    value, media_type = response_bytes(http, path, body, command, method=method)
    assert media_type == "application/json", (path, media_type)
    return json.loads(value)


def observe_until(http: Any, path: str, terminal: set[str], allowed: set[str]) -> dict[str, Any]:
    # Correctness is established by each actual owning response, never a delay.
    # The deadline is an existing technical resource budget, not a state oracle.
    deadline = time.monotonic() + 120
    origin = time.monotonic_ns()
    polls = 0
    first_poll_us = None
    while True:
        polls += 1
        value = request(http, path)
        if first_poll_us is None:
            # 第一次观测响应到达的时刻：与后续里程碑相减即可得到「首次可见状态」的独立耗时。
            first_poll_us = (time.monotonic_ns() - origin + 500) // 1000
        if value["state"] in terminal:
            elapsed_us = (time.monotonic_ns() - origin + 500) // 1000
            print(
                f"[observe-timing] path={path} elapsed_us={elapsed_us} first_poll_us={first_poll_us} "
                f"polls={polls} state={value['state']}",
                flush=True,
            )
            return value
        assert value["state"] in allowed, value
        if time.monotonic() >= deadline:
            # 预算耗尽是「首个失败原因」，必须先把已经观测到的事实打出来：轮询次数、
            # 首次可见状态时刻、最后一次非终态状态。清理（Host 终止与排空）在其后另行计时。
            print(
                f"[observe-timing] path={path} OUTCOME=deadline-exhausted polls={polls} "
                f"first_poll_us={first_poll_us} "
                f"elapsed_us={(time.monotonic_ns() - origin + 500) // 1000} last_state={value['state']}",
                flush=True,
            )
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
    stage("qualification-owner-begin")
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
    stage("qualification-owner-end")
    (output / "qualification.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    import re

    pid = re.search(r"FREEZE_TEST_BACKEND_PID ([0-9]+)", result.stdout)
    assert pid is not None
    # advisory锁排空是独立的「清理事实」窗口，与 owner 自身执行耗时分开计。
    stage("qualification-lock-drain-begin")
    wait_no_advisory_locks(dsn, int(pid.group(1)))
    stage("qualification-lock-drain-end")
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
    run: str,
    fresh: tuple[str, str] | None,
    scenario: str,
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
    phases = [(scenario, preparation)]
    if scenario == "crash-recover":
        assert fresh is not None
        phases = [
            ("crash-after-publication", preparation),
            ("recover-published", preparation),
            ("read-publication-withdrawal", preparation),
            ("resolve-unknown-commits", fresh[0]),
        ]
    committed = None
    for phase, phase_preparation in phases:
        path.write_text(
            json.dumps(
                {
                    "configuration": configuration,
                    "preparation": phase_preparation,
                    "fresh": fresh[0] if fresh is not None and scenario != "crash-recover" else None,
                }
            )
        )
        diagnostics = {"ONLYALPHA_DIAGNOSTICS_PATH": str(output / f"owner-{phase}.jsonl")}
        log = output / f"owner-{phase}.log"
        try:
            result = subprocess.run(
                [str(runner), "--exact", "actual_command_boundary", "--nocapture"],
                env={
                    **os.environ,
                    **diagnostics,
                    "ONLYALPHA_POSTGRES_DSN": dsn,
                    "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
                    "ONLYALPHA_FREEZE_TEST_PHASE": "backtest-owner:" + phase,
                    "ONLYALPHA_BACKTEST_OWNER_REQUEST": str(path),
                },
                capture_output=True,
                text=True,
                timeout=240,
            )
        except subprocess.TimeoutExpired as error:
            log.write_bytes((error.stdout or b"") + (error.stderr or b""))
            raise
        log.write_text(result.stdout + result.stderr)
        abrupt_exit = phase in (
            "crash-after-publication", "worker-exit-before-claim", "worker-exit-after-candidate",
            "worker-exit-during-insert",
        )
        assert result.returncode == (86 if abrupt_exit else 0), result.stdout + result.stderr
        if phase == "memory-completion":
            timings = [
                json.loads(line.removeprefix("FINITE_BACKTEST_CANDIDATE "))
                for line in result.stdout.splitlines()
                if line.startswith("FINITE_BACKTEST_CANDIDATE ")
            ]
            assert len(timings) == 1, result.stdout
            print({"finite_backtest_candidate": timings[0]}, flush=True)
        pids = re.findall(r"BACKTEST_OWNER_PID ([0-9]+)", result.stdout)
        assert len(pids) == 1, result.stdout + result.stderr
        fault_pids = re.findall(r"BACKTEST_FAULT_OWNER_PID ([0-9]+)", result.stdout)
        assert len(fault_pids) == (2 if phase == "resolve-unknown-commits" else 0), result.stdout
        assert len(set(pids + fault_pids)) == len(pids + fault_pids), result.stdout
        for pid in pids + fault_pids:
            wait_no_advisory_locks(dsn, int(pid))
        if phase == "resolve-unknown-commits":
            assert fresh is not None
            executions = [
                row
                for row in run_diagnostics(output / f"owner-{phase}.jsonl", fresh[1])
                if row.get("operation") == "backtest.execute_frozen"
            ]
            assert [(row["attempt"], row["event_kind"], row.get("outcome")) for row in executions] == [
                (1, "operation_start", None),
                (1, "operation_end", "ok"),
                (2, "operation_start", None),
                (2, "operation_end", "ok"),
            ], (fresh[1], executions)
        if not abrupt_exit:
            assert result.stdout.count("BACKTEST_OWNER_SCENARIO_CONFIRMED " + phase) == 1, result.stdout
        if abrupt_exit and phase != "crash-after-publication":
            lines = result.stdout.splitlines()
            exit_marker = f"BACKTEST_EXIT_AT {phase} {run}"
            assert lines.count(exit_marker) == 1, result.stdout
            starts = [line for line in lines if line.startswith("BACKTEST_EXECUTION_STARTED ")]
            expected = [] if phase == "worker-exit-before-claim" else [f"BACKTEST_EXECUTION_STARTED {run}"]
            assert starts == expected, result.stdout
            if starts:
                assert lines.index(starts[0]) < lines.index(exit_marker), result.stdout
        if phase == "crash-after-publication":
            assert f"BACKTEST_PUBLICATION_CONFIRMED_WITHOUT_ORIGINAL_GUARD {run}" in result.stdout
            committed = publication_identity(dsn, run)
        if phase in ("recover-published", "read-publication-withdrawal"):
            assert committed is not None
            assert publication_identity(dsn, run) == committed
            events = run_diagnostics(Path(diagnostics["ONLYALPHA_DIAGNOSTICS_PATH"]), run)
            assert not any(row.get("operation") == "backtest.execute_frozen" for row in events), events
            if phase == "read-publication-withdrawal":
                assert result.stdout.splitlines().count(f"BACKTEST_WITHDRAWAL_FENCED {run}") == 1
                reads = [
                    row.get("outcome") for row in events
                    if row.get("operation") == "http.backtest.read_publication"
                    and row["event_kind"] == "operation_end"
                ]
                assert reads == ["ok"], (run, reads)
        retained = binary.stat()
        assert (retained.st_dev, retained.st_ino, retained.st_size) == (
            selected.st_dev,
            selected.st_ino,
            selected.st_size,
        )
        assert binary.read_bytes() == original
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest


def build_web_assets(output: Path) -> Path:
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
    return assets


def read_backtest_publication(
    http: Any, run: str, preparation: str, pins: dict[str, Any], selected_sha: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    path = f"/api/v2/backtest/runs/{run}"
    details = request(http, path)
    assert details["run_id"] == run and details["state"] == "COMPLETED", details
    assert details["preparation_command_id"] == preparation, details
    assert details["report_status"]["state"] == "VERIFIED", details
    result = request(http, path + "/result")
    evidence = request(http, path + "/evidence")
    assert result["run_id"] == evidence["run_id"] == run
    assert result["strategy_fingerprint"] == details["strategy_fingerprint"] == pins["strategy_fingerprint"]
    assert evidence["preparation_command_id"] == preparation
    for key in ("freeze_relation_fingerprint", "qualification_decision_fingerprint", "promotion_fingerprint"):
        assert evidence[key] == pins[key], evidence
    publication = evidence["publication_fingerprint"]
    assert re.fullmatch(r"[0-9a-f]{64}", publication), evidence
    for key in ("evidence_fingerprint", "result_fingerprint", "determinism_fingerprint"):
        assert result[key] == publication
    manifest = evidence["manifest"]
    assert manifest["contract"] == "PG_JOB_RESULT_V1", manifest
    keys = ["causal_evidence", "close_curve", "economic_result", "execution_facts"]
    assert [item["key"] for item in manifest["members"]] == keys, manifest
    artifacts = {}
    for item in manifest["members"]:
        key = item["key"]
        raw, media_type = response_bytes(http, f"{path}/evidence/artifacts/{key}")
        assert media_type == "application/octet-stream", (key, media_type)
        assert hashlib.sha256(raw).hexdigest() == item["content_fingerprint"], item
        artifacts[key] = raw

    causal = json.loads(artifacts["causal_evidence"])["body"]
    assert causal["binding"]["scope"]["run_id"] == run
    assert causal["binding"]["kernel_artifact"] == causal["execution"]["native_image"]["artifact"] == selected_sha
    market = causal["binding"]["market"]
    economics = json.loads(artifacts["economic_result"])["body"]
    window = economics["preparation"]["window"]
    assert window["kind"] == "BAR_START_SAMPLE_CLOSED_EVENTS", window
    assert (int(window["source_bar_start_ns"]), int(window["source_bar_end_exclusive_ns"])) == (
        1735861200000000000,
        1735905600000000000,
    ), window
    assert (
        (int(market["start_ns"]), int(market["end_ns"]))
        == (int(window["dataset_event_start_ns"]), int(window["dataset_event_end_exclusive_ns"]))
        == (1735861260000000000, 1735905660000000000)
    ), (market, window)
    assert (market["rows"], market["warmup_rows"], market["sample_rows"]) == (740, 20, 720)
    facts = json.loads(artifacts["execution_facts"])["rows"]
    assert sum(row["family"] == "BAR" for row in facts) == 740
    assert sum(row["family"] == "OPEN" for row in facts) == 740
    curve = json.loads(artifacts["close_curve"])["rows"]
    assert [int(point["bar_end_ns"]) for point in curve] == list(
        range(1735862460000000000, 1735905600000000001, 60000000000)
    )
    assert [(point["at_ns"], point["nav"]) for point in result["curve"]] == [
        (point["bar_end_ns"], point["nav"]) for point in curve
    ]
    assert result["state"] == "COMPLETED" and len(result["curve"]) == 720
    assert result["sample"]["start_at"] == "2025-01-03T00:00:00Z"
    assert result["sample"]["end_at"] == "2025-01-03T12:00:00Z"
    assert Decimal(result["sample"]["quantity"]) == Decimal(".01")
    metrics = result["metrics"]
    assert (metrics["fill_count"], metrics["roundtrip_count"]) == (2, 1)
    for key, expected in [
        ("initial_equity", "10000"),
        ("final_equity", "9994.60119940"),
        ("fees", "1.99900060"),
        ("unrealized_pnl", "0"),
    ]:
        assert Decimal(metrics[key]) == Decimal(expected), metrics
    assert Decimal(result["baseline"]["final_equity"]) == Decimal("9998.7998")
    trades = result["trades"]
    assert [trade["ordinal"] for trade in trades] == [1, 2]
    assert [trade["side"] for trade in trades] == ["BUY", "SELL"]
    assert [Decimal(trade["price"]) for trade in trades] == [Decimal("100120.020000"), Decimal("99780.040000")]
    assert [trade["time_ns"] for trade in trades] == ["1735862460000000000", "1735862520000000000"]
    executions = [row["body"] for row in facts if row["family"] == "EXECUTION" and row["body"]["input"]["op"] == "FILL"]
    trades_fact = economics["economic_result"]["trades"]
    assert len(executions) == len(trades_fact) == len(trades) == 2
    for applied, economic, displayed in zip(executions, trades_fact, trades, strict=True):
        assert all(applied[key] == economic[key] for key in ("sequence", "transaction", "input"))
        payload = applied["input"]["payload"]
        assert (payload["order"], payload["trade"]) == (displayed["order_id"], displayed["trade_id"])
        assert payload["fees"]["charge_target"] == displayed["fee"]
    return result, evidence, artifacts


def publication_identity(dsn: str, run: str) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = db.execute(
            "SELECT state,specification_schema_version,admission_resolution_schema_version,"
            "evidence_fingerprint,result_fingerprint,determinism_fingerprint,"
            "specification_fingerprint,admission_resolution_fingerprint,revision,cancel_requested_at,finished_at "
            "FROM public.backtest_run WHERE run_id=%s",
            (run,),
        ).fetchone()
        attempts = db.execute(
            "SELECT attempt_id,attempt_number,state,fencing_token,worker_instance_id FROM public.backtest_run_attempt "
            "WHERE run_id=%s ORDER BY attempt_number",
            (run,),
        ).fetchall()
        publications = db.execute(
            "SELECT attempt_id,publication_fingerprint,manifest_payload,attempt_number,fence,worker_id,binding_fingerprint "
            "FROM public.job_publication WHERE job_kind='BACKTEST' AND run_id=%s",
            (run,),
        ).fetchall()
        members = db.execute(
            "SELECT member_key,content_fingerprint,descriptor,content FROM public.job_result_member "
            "WHERE job_kind='BACKTEST' AND run_id=%s ORDER BY member_key",
            (run,),
        ).fetchall()
    return row, attempts, publications, members


def run_diagnostics(path: Path, run: str) -> list[dict[str, Any]]:
    sessions = [json.loads(line) for line in path.read_text().splitlines()]
    assert sessions[0]["event_kind"] == "session_start", path
    assert {row["process_instance_id"] for row in sessions} == {sessions[0]["process_instance_id"]}, path
    return [row for row in sessions if row.get("run_id") == run]


def execution_attempts(events: list[dict[str, Any]]) -> list[int]:
    return [
        event["attempt"] for event in events
        if event.get("operation") == "backtest.execute_frozen" and event["event_kind"] == "operation_start"
    ]


def backtest_acceptance(dsn: str, run: str, command: str, *, owner: str = "local-developer") -> tuple[Any, ...]:
    with psycopg.connect(dsn) as db:
        identity = db.execute(
            "SELECT binding.owner_id, binding.binding_fingerprint, binding.payload, "
            "to_jsonb(admission), to_jsonb(receipt) "
            "FROM public.job_frozen_binding binding "
            "JOIN public.product_command_receipt receipt ON receipt.outcome_id=binding.run_id::text "
            "JOIN public.product_command_admission admission USING (command_id) "
            "WHERE binding.job_kind='BACKTEST' AND binding.run_id=%s AND receipt.command_id=%s "
            "AND receipt.command_kind='CREATE_BACKTEST_RUN' AND receipt.outcome_kind='BACKTEST_RUN'",
            (run, command),
        ).fetchone()
    assert identity is not None and identity[0] == owner, identity
    return identity


def cancel_receipts(dsn: str, run: str) -> dict[str, tuple[datetime, str]]:
    with psycopg.connect(dsn) as db:
        receipts = db.execute(
            "SELECT receipt.command_id::text,receipt.accepted_at,receipt.command_fingerprint "
            "FROM public.product_command_receipt AS receipt JOIN public.product_command_admission AS admission "
            "USING (command_id,command_kind,command_fingerprint) "
            "WHERE receipt.command_kind='CANCEL_BACKTEST_RUN' AND receipt.outcome_kind='BACKTEST_RUN' "
            "AND receipt.outcome_id=%s",
            (run,),
        ).fetchall()
    return {command: (accepted_at, fingerprint) for command, accepted_at, fingerprint in receipts}


def accept_with_concurrent_read(http: Any, dsn: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    from scripts.database_guard import assert_test_database

    database = assert_test_database(dsn)
    name = sql.Identifier("commit_probe_" + UUID(command).hex)
    base = "/api/v2/backtest/preparations"
    with psycopg.connect(dsn, autocommit=True) as db, ThreadPoolExecutor(max_workers=2) as requests:
        assert db.execute("SELECT current_database()").fetchone() == (database,)
        gate = db.execute("SELECT hashtextextended(%s,1)", (command,)).fetchone()[0]
        with db.transaction():
            # WITH HOLD 的结果在 COMMIT 时物化，受理逻辑提前检查延迟约束不会触发这把锁。
            db.execute(sql.SQL("""CREATE FUNCTION public.{}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    EXECUTE 'DECLARE acceptance_commit_probe NO SCROLL CURSOR WITH HOLD FOR
                        SELECT pg_catalog.pg_advisory_xact_lock({}::bigint)';
                    RETURN NEW;
                END $$""").format(name, sql.Literal(gate)))
            db.execute(sql.SQL("""CREATE TRIGGER {} AFTER INSERT ON public.product_command_receipt
                FOR EACH ROW WHEN (NEW.command_id = {}::uuid) EXECUTE FUNCTION public.{}()""").format(
                name, sql.Literal(command), name,
            ))
        try:
            def wait_for_waiter(pending: Future, blocker: int, key: int, statement: str) -> int:
                deadline = time.monotonic() + 15
                while True:
                    rows = db.execute("""SELECT l.pid FROM pg_catalog.pg_locks l JOIN pg_catalog.pg_stat_activity a
                        ON a.pid=l.pid WHERE a.datname=current_database() AND a.state='active'
                        AND upper(trim(trailing ';' from a.query))=%s AND l.locktype='advisory' AND NOT l.granted
                        AND l.classid=(%s::bigint >> 32 & 4294967295)::oid AND l.objid=(%s::bigint & 4294967295)::oid
                        AND l.objsubid=1 AND %s=ANY(pg_catalog.pg_blocking_pids(l.pid))""",
                        (statement, key, key, blocker)).fetchall()
                    if rows:
                        ((pid,),) = rows
                        return pid
                    if pending.done():
                        raise AssertionError(f"HTTP completed before {statement} lock observation: {pending.result()}")
                    assert time.monotonic() < deadline, (statement, blocker)

            with psycopg.connect(dsn) as barrier:
                blocker, command_key, _ = barrier.execute(
                    "SELECT pg_backend_pid(),hashtextextended(%s,0),pg_advisory_xact_lock(%s)", (command, gate),
                ).fetchone()
                post = requests.submit(request, http, base, payload, command)
                writer = wait_for_waiter(post, blocker, gate, "COMMIT")
                assert db.execute("SELECT 1 FROM public.product_command_receipt WHERE command_id=%s", (command,)).fetchone() is None
                get = requests.submit(request, http, f"{base}/commands/{command}")
                reader = wait_for_waiter(get, writer, command_key, "SELECT PG_ADVISORY_XACT_LOCK(HASHTEXTEXTENDED($1,0))")
            accepted, observed = post.result(), get.result()
            assert accepted['state'] == 'ACCEPTED' and observed['state'] in {'ACCEPTED', 'RUNNING', 'INPUT_PENDING', 'READY'}
            for key in ('command_id', 'backtest_command_id', 'reserved_run_id', 'accepted_at', 'origin', 'source'):
                assert observed[key] == accepted[key], key
            assert observed['command_id'] == command and observed['backtest_command_id'] == payload['backtest_command_id']
            assert observed['run_id'] is None and observed['backtest_outcome'] == 'NOT_SUBMITTED'
            ((owner, receipt_outcome_id),) = db.execute("""SELECT p.owner,r.outcome_id FROM public.research_preparation p
                JOIN public.product_command_receipt r USING (command_id) WHERE p.command_id=%s
                AND r.command_kind='PREPARE_BACKTEST' AND r.outcome_kind='RESEARCH_PREPARATION_OPERATION'
                AND r.outcome_id=p.accepted_fingerprint AND p.accepted_payload::jsonb->>'runtime_work_id'=%s""",
                (command, observed['reserved_run_id'])).fetchall()
            assert owner == 'local-developer'
            print(f"PREPARATION_COMMIT_READ command={command} future={observed['backtest_command_id']} "
                  f"run={observed['reserved_run_id']} owner={owner} receipt_outcome_id={receipt_outcome_id} barrier={blocker} "
                  f"writer_commit={writer} reader={reader} post={accepted['state']} get={observed['state']}", flush=True)
            return accepted
        finally:
            with db.transaction():
                db.execute(sql.SQL("DROP TRIGGER {} ON public.product_command_receipt").format(name))
                db.execute(sql.SQL("DROP FUNCTION public.{}()").format(name))


def assert_cancel_during_preparation(
    http: Any,
    dsn: str,
    payload: dict[str, Any],
    at_rules: threading.Event,
    release_rules: threading.Event,
) -> None:
    from packages.backend.tests.application.test_strategy_research_evidence import http_json

    preparation, cancel = str(uuid4()), str(uuid4())
    future = payload["backtest_command_id"]
    command_path = f"/api/v2/backtest/preparations/commands/{preparation}"
    cancellation = f"/api/v2/backtest/preparations/{preparation}/cancellation"
    with psycopg.connect(dsn, autocommit=True) as db:
        def original() -> tuple[Any, ...]:
            return db.execute(
                "SELECT owner,accepted_fingerprint,accepted_payload FROM research_preparation WHERE command_id=%s",
                (preparation,),
            ).fetchone()

        def receipt() -> list[tuple[Any, ...]]:
            return db.execute(
                "SELECT command_kind,outcome_kind,outcome_id,accepted_at,command_fingerprint "
                "FROM product_command_receipt WHERE command_id=%s",
                (cancel,),
            ).fetchall()

        try:
            accepted = request(http, "/api/v2/backtest/preparations", payload, preparation)
            assert accepted["command_id"] == preparation and accepted["run_id"] is None, accepted
            assert at_rules.wait(timeout=30), "original preparation did not request BTCUSDT rules"
            active = request(http, command_path)
            assert active["state"] == "RUNNING" and active["phase"] == "INPUTS", active
            assert active["backtest_outcome"] == "NOT_SUBMITTED" and active["run_id"] is None, active
            reserved = active["reserved_run_id"]
            assert reserved == accepted["reserved_run_id"]
            intent = original()
            assert intent[0] == "local-developer", intent
            body = {
                "schema_version": 1,
                "preparation_command_id": preparation,
                "expected_revision": active["revision"],
            }
            requested = request(http, cancellation, body, cancel)
            assert requested["state"] == "CANCEL_REQUESTED", requested
            assert int(requested["revision"]) == int(active["revision"]) + 1, requested
            committed = receipt()
            (first_receipt,) = committed
            assert first_receipt[:3] == (
                "CANCEL_BACKTEST_PREPARATION", "RESEARCH_PREPARATION_OPERATION", intent[1],
            ), committed
            assert request(http, cancellation, body, cancel) == requested
            assert receipt() == committed
        finally:
            release_rules.set()

        cancelled = observe_until(http, command_path, {"CANCELLED"}, {"CANCEL_REQUESTED"})
        assert cancelled["phase"] == "OWNER_DRAINED" and int(cancelled["revision"]) == int(active["revision"]) + 2
        replay = request(http, cancellation, body, cancel)
        for view in (requested, cancelled, replay):
            assert view["command_id"] == preparation and view["backtest_command_id"] == future, view
            assert view["reserved_run_id"] == reserved and view["run_id"] is None, view
            assert view["preparation_fingerprint"] is None and view["backtest_outcome"] == "NOT_SUBMITTED", view
        assert replay["state"] == "CANCELLED" and replay["revision"] == cancelled["revision"], replay
        status, refusal = http_json(
            http,
            "POST",
            f"/api/v2/backtest/preparations/{preparation}/submit",
            {"schema_version": 1, "preparation_command_id": preparation, "preparation_fingerprint": "0" * 64},
            {"Content-Type": "application/json", "Idempotency-Key": future},
        )
        assert (status, refusal["error"]["code"]) == (503, "RESEARCH_PREPARATION_INPUT_MISMATCH"), refusal
        assert original() == intent and receipt() == committed
        assert db.execute(
            "SELECT 1 FROM product_command_admission WHERE command_id=%s", (future,)
        ).fetchone() is None
    assert publication_identity(dsn, reserved) == (None, [], [], [])
    print(f"BACKTEST_PREPARATION_CANCEL_CONFIRMED preparation={preparation} reserved_run={reserved}", flush=True)


def recovery_identity(dsn: str, run: str) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        binding = db.execute(
            "SELECT owner_id, namespace_id, specification_fingerprint, admission_fingerprint, "
            "binding_fingerprint, payload FROM public.job_frozen_binding WHERE job_kind='BACKTEST' AND run_id=%s",
            (run,),
        ).fetchone()
        first_attempt = db.execute(
            "SELECT to_jsonb(a) FROM public.backtest_run_attempt a WHERE run_id=%s AND attempt_number=1",
            (run,),
        ).fetchone()
    assert binding is not None and binding[0] == "local-developer", binding
    assert first_attempt is not None
    return binding, first_attempt[0]


def assert_cold_cancelled_backtest(
    executable: Path,
    configuration: dict[str, Any],
    output: Path,
    dsn: str,
    run: str,
    preparation: str,
    scenario: str,
) -> None:
    before = publication_identity(dsn, run)
    row, attempts, publications, members = before
    recovering = scenario == "recover-cancel"
    expected_state = "CANCEL_REQUESTED" if recovering else "CANCELLED"
    assert row[0] == expected_state and row[3:6] == (None, None, None), row
    assert not publications and not members
    expected = [] if scenario == "queued-cancel" else [(1, "EXPIRED" if recovering else "CANCELLED")]
    assert [(number, state) for _, number, state, _, _ in attempts] == expected, attempts
    receipts = cancel_receipts(dsn, run)
    ((cancel_command, (accepted_at, _)),) = receipts.items()
    assert row[9] == accepted_at, row
    if recovering:
        assert row[10] is None
        identity = recovery_identity(dsn, run)
    else:
        assert row[10] >= accepted_at, row
    path = f"/api/v2/backtest/runs/{run}"
    diagnostics = output / "backtest-cold-cancelled-query.jsonl"
    with original_host(executable, configuration, output, diagnostics=diagnostics) as http:
        details = observe_until(http, path, {"CANCELLED"}, {"CANCEL_REQUESTED"} if recovering else set())
        assert details["run_id"] == run and details["preparation_command_id"] == preparation, details
        assert details["state"] == "CANCELLED" and details["cancellation_reason"] == "USER_REQUESTED", details
        assert datetime.fromisoformat(details["cancel_requested_at"]) == accepted_at, details
        assert details["report_status"]["state"] == "NOT_APPLICABLE", details
        if recovering:
            replay = request(http, f"{path}/cancellation", {"schema_version": 1, "run_id": run}, cancel_command)
            assert replay == {
                **details,
                "preparation_command_id": None,
                "worker_observation": replay["worker_observation"],
            }, replay
        for suffix in ("result", "evidence", "evidence/artifacts/causal_evidence"):
            assert_query_error(http, f"{path}/{suffix}", 409, "BACKTEST_RESULT_NOT_READY")
    after = publication_identity(dsn, run)
    events = run_diagnostics(diagnostics, run)
    assert not any(event.get("operation") == "backtest.execute_frozen" for event in events), events
    if recovering:
        completed, after_attempts, after_publications, after_members = after
        assert completed == ("CANCELLED", *row[1:8], row[8] + 1, accepted_at, completed[10]), completed
        assert completed[10] >= accepted_at, completed
        assert (after_attempts, after_publications, after_members) == (attempts, publications, members)
        assert recovery_identity(dsn, run) == identity
        assert cancel_receipts(dsn, run) == receipts
        operations = {event.get("operation") for event in events}
        assert "backtest.run_one" in operations and "backtest.run.claimed" not in operations, operations
        print(f"BACKTEST_RECOVERY_CANCEL_CONFIRMED run={run} attempts=1 resumed_executions=0", flush=True)
    else:
        assert after == before


@contextmanager
def missing_frozen_input(dsn: str, binding: dict[str, Any], scenario: str) -> Iterator[str]:
    from scripts.database_guard import assert_test_database

    database = "onlyalpha_dev_validation_test"
    if assert_test_database(dsn) != database:
        raise RuntimeError("controlled test database required")
    with psycopg.connect(dsn, autocommit=True) as db:
        if db.execute("SELECT current_database()").fetchone() != (database,):
            raise RuntimeError("controlled test database required")
        if scenario == "missing-program":
            (factor,) = binding["factor_bindings"]
            assert db.execute(
                "SELECT revision_fingerprint,program_fingerprint,parameters_fingerprint "
                "FROM public.factor_parameter_certificate WHERE certificate_fingerprint=%s",
                (factor["certificate"],),
            ).fetchone() == (factor["revision"], factor["program"], factor["parameters"])
            table, key, value = "factor_built_program", "program_fingerprint", factor["program"]
        else:
            assert scenario == "missing-market-seal", scenario
            table, key = "market_revision_seal", "revision_id"
            value = f"market-data-revision:{binding['market']['source_revision']}"
        relation = sql.Identifier("public", table)
        lookup = sql.SQL("SELECT row_to_json(stored)::text FROM {} AS stored WHERE {}=%s").format(
            relation, sql.Identifier(key)
        )
        (saved,) = db.execute(lookup, (value,)).fetchone()
        delete = sql.SQL("DELETE FROM {} AS stored WHERE {}=%s RETURNING row_to_json(stored)::text").format(
            relation, sql.Identifier(key)
        )
        restore = sql.SQL(
            "INSERT INTO {0} SELECT (json_populate_record(NULL::{0}, %s::json)).*"
        ).format(relation)
        try:
            with db.transaction():
                # The fault must leave the original certificate and frozen binding in place.
                db.execute("SET LOCAL session_replication_role = replica")
                assert db.execute(delete, (value,)).fetchall() == [(saved,)]
            assert db.execute(lookup, (value,)).fetchone() is None
            yield value
            assert db.execute(lookup, (value,)).fetchone() is None
        finally:
            if db.execute(lookup, (value,)).fetchone() is None:
                db.execute(restore, (saved,))
            assert db.execute(lookup, (value,)).fetchone() == (saved,)


@contextmanager
def missing_frozen_market_row(
    dsn: str, database: MarketStorageInputs, market: dict[str, Any]
) -> Iterator[str]:
    from packages.backend.tests.application.test_market_storage_postgres_clickhouse import (
        ClickHouseObservations,
        _quote,
    )
    from scripts.database_guard import assert_test_database

    test_database = "onlyalpha_dev_validation_test"
    if assert_test_database(dsn) != test_database or not re.fullmatch(
        r"onlyalpha_test_native_market_storage_[0-9a-f]{32}", database.config.database
    ):
        raise RuntimeError("controlled test databases required")

    def catalog_snapshot() -> tuple[Any, ...]:
        with psycopg.connect(dsn) as db:
            if db.execute("SELECT current_database()").fetchone() != (test_database,):
                raise RuntimeError("controlled test database required")
            (original,) = db.execute(
                "SELECT rs.segment_id, rs.segment_content_hash, row_to_json(r), row_to_json(m), "
                "row_to_json(s), row_to_json(p) FROM market_data_revision r "
                "JOIN market_coverage_manifest m ON m.manifest_id = r.manifest_id "
                "JOIN market_revision_seal s ON s.revision_id = r.revision_id "
                "JOIN market_revision_segment rs ON rs.revision_id = r.revision_id "
                "JOIN market_coverage_manifest_segment ms ON ms.manifest_id = m.manifest_id "
                "AND (ms.ordinal, ms.segment_id, ms.segment_content_hash) = "
                "(rs.ordinal, rs.segment_id, rs.segment_content_hash) "
                "JOIN market_segment_physical_proof p ON p.segment_id = rs.segment_id "
                "WHERE r.revision_fingerprint = %s",
                (market["source_revision"],),
            ).fetchall()
            return original

    original = catalog_snapshot()
    segment_id, content_hash, _, _, _, proof = original
    (bar_partition,) = (part for part in proof["proof"]["partitions"] if part["table"] == "market_bar")
    storage = ClickHouseObservations(database.config)
    segment = f"segment_id = {_quote(segment_id)} AND segment_content_hash = {_quote(content_hash)}"
    query = (
        "SELECT canonical_fact_id, raw_event_id, bar_start_ns, bar_end_ns, record_hash "
        f"FROM market_bar WHERE {segment} ORDER BY bar_start_ns, canonical_fact_id, raw_event_id"
    )
    rows = storage.query_json(query)
    assert len(rows) == bar_partition["row_count"]
    selected = next(
        row for row in rows
        if market["start_ns"] <= int(row["bar_start_ns"]) < int(row["bar_end_ns"]) <= market["end_ns"]
    )
    retained = tuple(row for row in rows if row != selected)
    assert len(retained) == len(rows) - 1
    fact = selected["canonical_fact_id"]
    raw = selected["raw_event_id"]
    storage.execute(
        f"ALTER TABLE market_bar DELETE WHERE {segment} AND canonical_fact_id = {_quote(fact)} "
        f"AND raw_event_id = {_quote(raw)} SETTINGS mutations_sync=2"
    )
    assert storage.query_json(query) == retained
    assert catalog_snapshot() == original
    yield fact
    assert storage.query_json(query) == retained
    assert catalog_snapshot() == original


def assert_missing_frozen_backtest_input(
    executable: Path,
    configuration: dict[str, Any],
    output: Path,
    dsn: str,
    run: str,
    preparation: str,
    scenario: str,
    database: MarketStorageInputs,
) -> None:
    row, attempts, publications, members = publication_identity(dsn, run)
    assert row[0] == "RUNNING" and row[3:6] == (None, None, None) and row[9:] == (None, None), row
    (original,) = attempts
    assert original[1:4] == (1, "ACTIVE", 1), original
    assert not publications and not members
    frozen, initial_attempt = recovery_identity(dsn, run)
    binding = json.loads(frozen[-1])
    assert frozen[2:4] == row[6:8] and binding["scope"]["run_id"] == run
    path = f"/api/v2/backtest/runs/{run}"
    diagnostics = output / "backtest-missing-input-recovery.jsonl"
    if scenario == "missing-market-row":
        assert configuration["clickhouse_database"] == database.config.database
        missing_input = missing_frozen_market_row(dsn, database, binding["market"])
        code = "JOB_INPUT_MISMATCH"
    else:
        missing_input = missing_frozen_input(dsn, binding, scenario)
        code = "JOB_INPUT_MISSING_EVIDENCE"
    with missing_input as missing:
        with original_host(executable, configuration, output, diagnostics=diagnostics) as http:
            failed = observe_until(http, path, {"FAILED"}, {"RUNNING"})
            assert failed["run_id"] == run and failed["preparation_command_id"] == preparation, failed
            assert failed["report_status"]["state"] == "NOT_APPLICABLE", failed
            for suffix in ("result", "evidence"):
                assert_query_error(http, f"{path}/{suffix}", 409, "BACKTEST_RESULT_NOT_READY")
    terminal, attempts, publications, members = publication_identity(dsn, run)
    assert terminal[:10] == ("FAILED", *row[1:8], row[8] + 1, None), terminal
    assert not publications and not members
    first, second = attempts
    assert first == (*original[:2], "EXPIRED", *original[3:]), attempts
    assert second[1:4] == (2, "FAILED", 2) and second[0] != first[0] and second[4] != first[4], attempts
    after_binding, expired_attempt = recovery_identity(dsn, run)
    assert after_binding == frozen
    for key in ("claimed_at", "last_heartbeat_at", "lease_expires_at"):
        assert expired_attempt[key] == initial_attempt[key], expired_attempt
    with psycopg.connect(dsn) as db:
        run_failure = db.execute(
            "SELECT failure_phase,failure_code FROM public.backtest_run WHERE run_id=%s", (run,)
        ).fetchone()
        attempt_failure = db.execute(
            "SELECT failure_code,finished_at FROM public.backtest_run_attempt WHERE attempt_id=%s", (second[0],)
        ).fetchone()
    assert (run_failure, attempt_failure) == (("ADMISSION", code), (code, terminal[10])), (
        scenario, run, run_failure, attempt_failure
    )
    events = run_diagnostics(diagnostics, run)
    assert [event["attempt"] for event in events if event.get("operation") == "backtest.run.claimed"] == [2], events
    assert not any(event.get("operation") == "backtest.execute_frozen" for event in events), events
    print(f"BACKTEST_FROZEN_INPUT_MISSING run={run} scenario={scenario} input={missing} executions=0", flush=True)


def assert_backtest_attempts_exhausted(
    executable: Path,
    configuration: dict[str, Any],
    output: Path,
    dsn: str,
    run: str,
    preparation: str,
    command: str,
) -> None:
    before, claims, publications, members = publication_identity(dsn, run)
    assert before[0] == "RUNNING" and before[3:6] == (None, None, None) and before[9:] == (None, None), before
    assert [claim[1:4] for claim in claims] == [(1, "EXPIRED", 1), (2, "EXPIRED", 2), (3, "ACTIVE", 3)], claims
    assert len({claim[0] for claim in claims}) == len({claim[4] for claim in claims}) == 3, claims
    assert not publications and not members
    acceptance = backtest_acceptance(dsn, run, command)
    original_events = run_diagnostics(output / "owner-attempts-exhausted.jsonl", run)
    assert [event["attempt"] for event in original_events if event.get("operation") == "backtest.run.claimed"] == [1, 2, 3]
    assert execution_attempts(original_events) == [], original_events

    diagnostics = output / "backtest-attempts-exhausted-recovery.jsonl"
    path = f"/api/v2/backtest/runs/{run}"
    with original_host(executable, configuration, output, diagnostics=diagnostics) as http:
        failed = observe_until(http, path, {"FAILED"}, {"RUNNING"})
        assert failed["run_id"] == run and failed["preparation_command_id"] == preparation, failed
        assert failed["report_status"]["state"] == "NOT_APPLICABLE", failed
        history = request(http, f"/api/v2/backtest/preparations/commands/{preparation}")
        assert history["run_id"] == run and history["backtest_command_id"] == command, history
        for suffix in ("result", "evidence"):
            assert_query_error(http, f"{path}/{suffix}", 409, "BACKTEST_RESULT_NOT_READY")

    terminal, attempts, publications, members = publication_identity(dsn, run)
    assert terminal[:10] == ("FAILED", *before[1:8], before[8] + 1, None), terminal
    assert attempts == [(*claim[:2], "EXPIRED", *claim[3:]) for claim in claims], attempts
    assert not publications and not members
    assert backtest_acceptance(dsn, run, command) == acceptance
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT run_id::text FROM public.backtest_run").fetchall() == [(run,)]
        assert db.execute(
            "SELECT failure_phase, failure_code FROM public.backtest_run WHERE run_id=%s", (run,),
        ).fetchone() == ("OPERATIONAL", "BACKTEST_ATTEMPTS_EXHAUSTED")
        order = db.execute(
            "SELECT lease_expires_at <= finished_at AND finished_at <= "
            "coalesce(lead(claimed_at) OVER (ORDER BY attempt_number), %s) "
            "FROM public.backtest_run_attempt WHERE run_id=%s ORDER BY attempt_number",
            (terminal[10], run),
        ).fetchall()
        assert order == [(True,), (True,), (True,)], order
    events = run_diagnostics(diagnostics, run)
    assert not any(event.get("operation") == "backtest.run.claimed" for event in events), events
    assert execution_attempts(events) == [], events
    print(f"BACKTEST_ATTEMPTS_EXHAUSTED run={run} attempts=3 executions=0", flush=True)


def assert_query_error(http: Any, path: str, status: int, code: str) -> None:
    origin = "http://127.0.0.1:5173"
    with pytest.raises(HTTPError) as error:
        http.open(Request(origin + path, headers={"Origin": origin, "Accept": "application/json"}), timeout=15)
    with error.value as response:
        assert response.code == status, (path, response.code)
        assert response.headers.get_content_type() == "application/json"
        assert response.headers.get("Content-Disposition") is None
        body = json.load(response)
        assert body == {"schema_version": 1, "error": {"phase": "QUERY", "code": code, "detail": code}}, body


def omit_first_trade_fee(
    points: list[tuple[str | None, dict[str, Any]]],
    trade_causes: tuple[str, str],
    trade_fees: tuple[Decimal, Decimal],
) -> None:
    first, second = [index for index, (cause, _) in enumerate(points) if cause in trade_causes]
    assert 0 < first < second and (points[first][0], points[second][0]) == trade_causes
    previous = points[first - 1][1]["fees"]
    first_total = Decimal(previous) + trade_fees[0]
    assert Decimal(points[second][1]["fees"]) == Decimal(previous) + sum(trade_fees)
    for _, snapshot in points[first:second]:
        assert Decimal(snapshot["fees"]) == first_total
        snapshot["fees"] = previous


def alter_backtest_economics(result: dict[str, Any], fault: str) -> None:
    if fault == "numeric final equity":
        performance = result["runtime_performance"]
        summary = performance["summary"]
        assert isinstance(summary["final_equity"], str)
        original_id = performance.pop("id")
        assert original_id == f"AP-{only_canonical_fingerprint(performance)}"
        summary["final_equity"] = 10000
        performance["id"] = f"AP-{only_canonical_fingerprint(performance)}"
        return

    first, second = result["trades"]
    assert first["transaction"] != second["transaction"]
    if fault == "different trade transaction":
        first["transaction"] = second["transaction"]
        return

    first_input, second_input = first["input"], second["input"]
    assert first_input["op"] == second_input["op"] == "FILL"
    first_fill, second_fill = first_input["payload"], second_input["payload"]
    cluster = first_input["cluster"]
    assert second_input["cluster"] == cluster and first_fill["order"] != second_fill["order"]
    trade_causes = (only_canonical_fingerprint(first_input), only_canonical_fingerprint(second_input))
    assert (first["transaction"], second["transaction"]) == tuple(f"ETX-{cause}" for cause in trade_causes)

    if fault in {"account fee prefix", "ledger fee prefix"}:
        def net_fee(fill: dict[str, Any]) -> Decimal:
            return Decimal(fill["fees"]["charge_target"]) - Decimal(fill["fees"]["rebate_target"])

        trade_fees = (net_fee(first_fill), net_fee(second_fill))
        assert all(fee > 0 for fee in trade_fees), trade_fees

    if fault in {"account fee prefix", "account command cause"}:
        performance = result["runtime_performance"]
        timeline = performance["timeline"]
        assert result["account_equity_timeline"] == timeline
        original_id = performance.pop("id")
        assert original_id == f"AP-{only_canonical_fingerprint(performance)}"
        if fault == "account fee prefix":
            points = [
                (point["provenance"]["upstream_cause"] if point["source"] == "TRADE" else None, point["snapshot"])
                for point in timeline
            ]
            omit_first_trade_fee(points, trade_causes, trade_fees)
        else:
            (point,) = (
                point for point in timeline
                if point["source"] == "TRADE" and point["provenance"]["upstream_cause"] == trade_causes[0]
            )
            provenance = point["provenance"]
            assert point["cause"] == provenance["cause"] and provenance["kind"] == "TRADE"
            wrong_cause = "f" * 64
            assert point["cause"] != wrong_cause
            point["cause"] = provenance["cause"] = wrong_cause
        performance["id"] = f"AP-{only_canonical_fingerprint(performance)}"
        result["account_equity_timeline"] = timeline
        return

    if fault in {"closed position cost", "closed allocation cost", "closed position average", "closed allocation average"}:
        key = "final_positions" if fault.startswith("closed position") else "final_allocations"
        (row,) = result[key]
        position = row["snapshot"]
        assert position["status"] == "CLOSED" and Decimal(position["quantity"]) == 0
        if fault.endswith("cost"):
            assert Decimal(position["cost"]) == 0
            position["cost"] = "1"
        else:
            assert position["average"] is None and Decimal(first_fill["price"]) > 0
            position["average"] = first_fill["price"]
        return

    (ledger_timeline,) = (timeline for timeline in result["cluster_equity_timelines"] if timeline["cluster"] == cluster)
    initial, *occurrences = ledger_timeline["points"]
    assert initial["source"] == "LEDGER_CREATED"
    if fault == "ledger fee prefix":
        points = [(None, initial["snapshot"])] + [
            (entry["point"]["cause"], entry["point"]["snapshot"]) for entry in occurrences
        ]
        omit_first_trade_fee(points, trade_causes, trade_fees)
        return

    assert fault in {"ledger cumulative return", "ledger daily return"}, fault
    field = "simple_return" if fault == "ledger cumulative return" else "daily_return"
    (final_ledger,) = (ledger for ledger in result["final_ledgers"] if ledger["cluster"] == cluster)
    (cluster_result,) = (row for row in result["cluster_results"] if row["cluster"] == cluster)
    last_snapshot = occurrences[-1]["point"]["snapshot"]
    assert cluster_result["final_ledger"] == final_ledger
    original_return = final_ledger[field]
    wrong_return = "1.00000000"
    assert last_snapshot[field] == original_return and isinstance(original_return, str)
    assert Decimal(original_return) != Decimal(wrong_return)
    last_snapshot[field] = final_ledger[field] = wrong_return
    cluster_result["final_ledger"] = final_ledger
    if field == "simple_return":
        summary = cluster_result["cluster_performance"]["summary"]
        assert summary[field] == original_return
        summary[field] = wrong_return


def assert_backtest_query_refusals(http: Any, dsn: str, run: str, snapshot: tuple[Any, ...]) -> tuple[int, int]:
    path = f"/api/v2/backtest/runs/{run}"
    resources = (path + "/result", path + "/evidence", path + "/evidence/artifacts/causal_evidence")
    for resource in (path, *resources):
        assert_query_error(build_opener(), resource, 401, "LOCAL_READ_UNAUTHORIZED")
        assert_query_error(http, resource.replace(run, str(uuid4()), 1), 404, "BACKTEST_RUN_NOT_FOUND")

    def reject_publication(code: str, status: int = 503) -> None:
        detail = request(http, path)
        assert detail["run_id"] == run and detail["state"] == "COMPLETED", detail
        assert detail["report_status"] == {"state": "UNAVAILABLE", "code": code}, detail
        for resource in resources:
            assert_query_error(http, resource, status, code)

    with psycopg.connect(dsn, autocommit=True) as db:
        assert db.info.dbname == "onlyalpha_dev_validation_test"
        with db.transaction():
            db.execute("SET LOCAL lock_timeout='2s'")
            db.execute("LOCK TABLE public.job_result_member IN ACCESS EXCLUSIVE MODE")
            reject_publication("JOB_RESULT_UNAVAILABLE")

        db.execute("REVOKE SELECT ON public.job_result_member FROM onlyalpha_job_reader")
        try:
            reject_publication("JOB_RESULT_ACCESS_DENIED", 403)
        finally:
            db.execute("GRANT SELECT ON public.job_result_member TO onlyalpha_job_reader")

        with db.transaction():
            db.execute(
                sql.SQL(
                    "CREATE POLICY backtest_test_hidden_publication ON public.job_publication "
                    "FOR SELECT TO onlyalpha_job_reader USING (job_kind <> 'BACKTEST' OR run_id <> {}::uuid)"
                ).format(sql.Literal(run))
            )
            db.execute("ALTER TABLE public.job_publication ENABLE ROW LEVEL SECURITY")
        try:
            reject_publication("JOB_RESULT_MISSING_EVIDENCE")
        finally:
            with db.transaction():
                db.execute("ALTER TABLE public.job_publication DISABLE ROW LEVEL SECURITY")
                db.execute("DROP POLICY backtest_test_hidden_publication ON public.job_publication")

        ((key, digest, _, content),) = (row for row in snapshot[3] if row[0] == "causal_evidence")

        def replace_member(payload: str, fingerprint: str) -> None:
            with db.transaction():
                db.execute("ALTER TABLE public.job_result_member DISABLE TRIGGER job_result_member_immutable")
                changed = db.execute(
                    "UPDATE public.job_result_member SET content=%s,content_fingerprint=%s "
                    "WHERE job_kind='BACKTEST' AND run_id=%s AND member_key=%s",
                    (payload, fingerprint, run, key),
                )
                assert changed.rowcount == 1
                db.execute("ALTER TABLE public.job_result_member ENABLE TRIGGER job_result_member_immutable")

        replace_member("{}", hashlib.sha256(b"{}").hexdigest())
        try:
            reject_publication("JOB_RESULT_CORRUPT")
        finally:
            replace_member(content, digest)

        def replace_winner(attempt: UUID) -> None:
            with db.transaction():
                db.execute("ALTER TABLE public.job_publication DISABLE TRIGGER job_publication_immutable")
                changed = db.execute(
                    "UPDATE public.job_publication SET attempt_id=%s WHERE job_kind='BACKTEST' AND run_id=%s",
                    (attempt, run),
                )
                assert changed.rowcount == 1
                db.execute("ALTER TABLE public.job_publication ENABLE TRIGGER job_publication_immutable")

        assert [row[2] for row in snapshot[1]] == ["EXPIRED", "SUCCEEDED"]
        predecessor = snapshot[1][0][0]
        finished_at, before_expiry = db.execute(
            "SELECT finished_at, lease_expires_at - interval '1 microsecond' FROM public.backtest_run_attempt "
            "WHERE attempt_id=%s AND run_id=%s AND state='EXPIRED' AND finished_at>=lease_expires_at",
            (predecessor, run),
        ).fetchone()

        def set_predecessor_finish(at: datetime) -> None:
            with db.transaction():
                db.execute("ALTER TABLE public.backtest_run_attempt DISABLE TRIGGER job_backtest_attempt_closure")
                changed = db.execute(
                    "UPDATE public.backtest_run_attempt SET finished_at=%s WHERE attempt_id=%s AND run_id=%s AND state='EXPIRED'",
                    (at, predecessor, run),
                )
                assert changed.rowcount == 1
                db.execute("ALTER TABLE public.backtest_run_attempt ENABLE TRIGGER job_backtest_attempt_closure")

        set_predecessor_finish(before_expiry)
        try:
            reject_publication("JOB_RESULT_CORRUPT")
        finally:
            set_predecessor_finish(finished_at)

        replace_winner(predecessor)
        try:
            reject_publication("JOB_RESULT_CORRUPT")
        finally:
            replace_winner(snapshot[2][0][0])

        originals = {key: (content, digest, descriptor) for key, digest, descriptor, content in snapshot[3]}
        ((_, original_fingerprint, original_manifest, *_),) = snapshot[2]
        assert snapshot[0][3:6] == (original_fingerprint,) * 3
        original_entries = {entry["key"]: entry for entry in json.loads(original_manifest)["members"]}
        assert original_entries.keys() == originals.keys()
        assert only_canonical_fingerprint(json.loads(original_manifest)) == original_fingerprint
        opening_member = None
        for key, (content, digest, descriptor) in originals.items():
            entry = original_entries[key]
            assert hashlib.sha256(content.encode()).hexdigest() == digest == entry["content_fingerprint"]
            assert hashlib.sha256(descriptor.encode()).hexdigest() == entry["descriptor_fingerprint"]
            if opening_member is None and json.loads(descriptor)["kind"] == "EXECUTION_FACTS":
                for index, row in enumerate(json.loads(content)["rows"]):
                    if row["family"] == "OPEN" and row["body"]["status"] == "FILLED":
                        opening_member = (key, index)
                        break
        assert opening_member is not None

        def replace_projection_members(
            members: dict[str, tuple[str, str, str]], manifest: str, fingerprint: str
        ) -> None:
            # The untouched membership and byte digests must still pass the repository reader.
            with db.transaction():
                triggers = (
                    ("job_result_member", "job_result_member_immutable"),
                    ("job_publication", "job_publication_immutable"),
                    ("backtest_run", "job_backtest_run_closure"),
                )
                for table, trigger in triggers:
                    db.execute(sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(
                        sql.Identifier(table), sql.Identifier(trigger)
                    ))
                for key, (content, digest, descriptor) in members.items():
                    changed = db.execute(
                        "UPDATE public.job_result_member SET content=%s,content_fingerprint=%s,descriptor=%s "
                        "WHERE job_kind='BACKTEST' AND run_id=%s AND member_key=%s",
                        (content, digest, descriptor, run, key),
                    )
                    assert changed.rowcount == 1
                changed = db.execute(
                    "UPDATE public.job_publication SET manifest_payload=%s,publication_fingerprint=%s "
                    "WHERE job_kind='BACKTEST' AND run_id=%s",
                    (manifest, fingerprint, run),
                )
                assert changed.rowcount == 1
                changed = db.execute(
                    "UPDATE public.backtest_run SET evidence_fingerprint=%s,result_fingerprint=%s,"
                    "determinism_fingerprint=%s WHERE run_id=%s",
                    (fingerprint, fingerprint, fingerprint, run),
                )
                assert changed.rowcount == 1
                for table, trigger in triggers:
                    db.execute(sql.SQL("ALTER TABLE public.{} ENABLE TRIGGER {}").format(
                        sql.Identifier(table), sql.Identifier(trigger)
                    ))

        faults = (
            "numeric final equity",
            "different trade transaction",
            "account fee prefix",
            "ledger fee prefix",
            "account command cause",
            "closed position cost",
            "closed allocation cost",
            "closed position average",
            "closed allocation average",
            "ledger cumulative return",
            "ledger daily return",
        )
        settlement_faults = ("admission settlement policy", "execution settlement policy")
        for fault in (*faults, *settlement_faults):
            if fault in settlement_faults:
                key, index = opening_member
                facts = json.loads(originals[key][0])
                opening = facts["rows"][index]["body"]
                if fault == "admission settlement policy":
                    policy = opening["admission"]["settlement_policy"]
                    policy["asset_trade_available"] += 1
                    opening["economic_evidence"]["settlement_policy"] = policy.copy()
                else:
                    opening["economic_evidence"]["settlement_policy"]["cash_withdrawable"] += 1
                facts["axis"][index][2] = only_canonical_fingerprint(opening)
                descriptor = json.loads(originals[key][2])
                descriptor["axis"] = only_canonical_fingerprint(facts["axis"])
                payload = facts
                descriptor_raw = only_canonical_json(descriptor)
            else:
                key = "economic_result"
                payload = json.loads(originals[key][0])
                alter_backtest_economics(payload["body"]["economic_result"], fault)
                descriptor_raw = originals[key][2]
            fingerprint = only_canonical_fingerprint(payload)
            assert fingerprint != originals[key][1], fault
            causal = json.loads(originals["causal_evidence"][0])
            (reference,) = (item for item in causal["body"]["members"] if item["key"] == key)
            assert reference["content"] == originals[key][1]
            reference["content"] = fingerprint
            members = {
                key: (only_canonical_json(payload), fingerprint, descriptor_raw),
                "causal_evidence": (
                    only_canonical_json(causal), only_canonical_fingerprint(causal), originals["causal_evidence"][2]
                ),
            }
            manifest = json.loads(original_manifest)
            for member in manifest["members"]:
                if member["key"] in members:
                    _, digest, descriptor = members[member["key"]]
                    member["content_fingerprint"] = digest
                    member["descriptor_fingerprint"] = hashlib.sha256(descriptor.encode()).hexdigest()
            replace_projection_members(members, only_canonical_json(manifest), only_canonical_fingerprint(manifest))
            try:
                reject_publication("JOB_RESULT_CORRUPT")
            finally:
                replace_projection_members({key: originals[key] for key in members}, original_manifest, original_fingerprint)
                assert publication_identity(dsn, run) == snapshot, fault
    assert publication_identity(dsn, run) == snapshot
    entry_points = 1 + len(resources)
    return len(faults) * entry_points, len(settlement_faults) * entry_points


def assert_cold_backtest_publication(
    executable: Path,
    configuration: dict[str, Any],
    output: Path,
    dsn: str,
    run: str,
    preparation: str,
    pins: dict[str, Any],
    selected_sha: str,
    *,
    attempt_states: tuple[str, ...] = ("SUCCEEDED",),
    late_cancel: bool = False,
    prior_cancel: bool = False,
    check_refusals: bool = False,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    before = publication_identity(dsn, run)
    expected_receipts = cancel_receipts(dsn, run) if late_cancel else None
    if expected_receipts is not None:
        requested_at, finished_at = before[0][9:11]
        if prior_cancel:
            ((accepted_at, _),) = expected_receipts.values()
            assert accepted_at == requested_at and accepted_at <= finished_at
        else:
            assert requested_at is None and not expected_receipts
    expected = None
    for host, reads in enumerate((2, 1), start=1):
        diagnostics = output / f"backtest-cold-query-{run}-{host}.jsonl"
        body_refusals = (0, 0)
        with original_host(executable, configuration, output, diagnostics=diagnostics) as http:
            if expected_receipts is not None and host == 1:
                command = str(uuid4())
                assert command not in expected_receipts
                path = f"/api/v2/backtest/runs/{run}/cancellation"
                body = {"schema_version": 1, "run_id": run}
                for submission in range(2):
                    cancelled = request(http, path, body, command)
                    assert cancelled["run_id"] == run and cancelled["state"] == "COMPLETED", cancelled
                    assert cancelled.get("cancel_requested_at") is None and cancelled.get("cancellation_reason") is None
                    observed = cancel_receipts(dsn, run)
                    if submission == 0:
                        expected_receipts[command] = observed[command]
                    assert observed == expected_receipts
                    assert publication_identity(dsn, run) == before
            if check_refusals and host == 1:
                body_refusals = assert_backtest_query_refusals(http, dsn, run, before)
            for _ in range(reads):
                actual = read_backtest_publication(http, run, preparation, pins, selected_sha)
                if expected is None:
                    expected = actual
                assert actual == expected, (run, host)
        events = run_diagnostics(diagnostics, run)
        completed_reads = [
            row
            for row in events
            if row.get("operation") == "http.backtest.read_publication"
            and row["event_kind"] == "operation_end"
            and row["outcome"] == "ok"
        ]
        assert len(completed_reads) == reads * 7, (run, host, len(completed_reads))
        rejected_bodies = tuple(
            sum(
                row.get("operation") == operation and row["event_kind"] == "operation_end" and row["outcome"] == "failed"
                for row in events
            )
            for operation in ("backtest.verify_economic_result", "backtest.verify_settlement_policy")
        )
        assert rejected_bodies == body_refusals, (run, host, rejected_bodies, body_refusals)
        assert not any(row.get("operation") == "backtest.execute_frozen" for row in events), events
    assert expected is not None
    result, evidence, artifacts = expected
    publication = evidence["publication_fingerprint"]
    row, attempts, publications, members = before
    assert row[:6] == ("COMPLETED", 3, 2, publication, publication, publication), row
    assert [(number, state) for _, number, state, _, _ in attempts] == list(enumerate(attempt_states, 1)), attempts
    attempt_id, attempt_number, _, fence, worker = attempts[-1]
    assert all(previous[3] < current[3] for previous, current in itertools.pairwise(attempts)), attempts
    ((published_attempt, fingerprint, manifest, published_number, published_fence, published_worker, _),) = publications
    assert (published_attempt, published_number, published_fence, published_worker) == (
        attempt_id,
        attempt_number,
        fence,
        worker,
    )
    assert fingerprint == publication
    assert hashlib.sha256(manifest.encode()).hexdigest() == publication
    assert json.loads(manifest) == evidence["manifest"]
    assert [(key, digest) for key, digest, _, _ in members] == [
        (member["key"], member["content_fingerprint"]) for member in evidence["manifest"]["members"]
    ]
    assert {key: content.encode() for key, _, _, content in members} == artifacts
    assert publication_identity(dsn, run) == before
    if expected_receipts is not None:
        assert cancel_receipts(dsn, run) == expected_receipts
    return result, artifacts


def prepare_comparison(http: Any, payload: dict[str, Any]) -> tuple[str, str]:
    command, future = str(uuid4()), str(uuid4())
    accepted = request(http, "/api/v2/backtest/preparations", {**payload, "backtest_command_id": future}, command)
    assert accepted["command_id"] == command and accepted["backtest_command_id"] == future
    ready = observe_until(
        http, f"/api/v2/backtest/preparations/commands/{command}", {"READY"}, {"ACCEPTED", "RUNNING", "INPUT_PENDING"}
    )
    assert ready["run_id"] is None and ready["backtest_outcome"] == "NOT_SUBMITTED"
    return command, ready["reserved_run_id"]


def submit_comparison(http: Any, preparation: str, run: str) -> str:
    ready = request(http, f"/api/v2/backtest/preparations/commands/{preparation}")
    assert ready["reserved_run_id"] == run and ready["state"] == "READY", ready
    submitted = request(
        http, f"/api/v2/backtest/preparations/{preparation}/submit",
        {"schema_version": 1, "preparation_command_id": preparation, "preparation_fingerprint": ready["preparation_fingerprint"]},
        ready["backtest_command_id"],
    )
    assert submitted["state"] == "ACCEPTED" and submitted["run_id"] == run, submitted
    assert submitted["backtest_command_id"] == ready["backtest_command_id"], submitted
    return ready["backtest_command_id"]


def run_comparison(http: Any, preparation: str, run: str) -> None:
    submit_comparison(http, preparation, run)
    observe_until(http, f"/api/v2/backtest/runs/{run}", {"COMPLETED"}, {"QUEUED", "RUNNING"})


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
    *,
    web_assets: Path | None = None,
) -> None:
    output.mkdir()
    # 原生 Host 链路是外层用例的一个子阶段，共用同一张表：与 native-dispatch-* 是包含关系。
    stage("native-chain-begin")
    # PG 发布模式的冻结语义身份只能由生产 Freeze 入口给出，因此依赖冻结关系的
    # qualification 推迟到 Host 起来、正式 Freeze 成功之后再做。
    publication = frozen.get("publication")
    if publication is None:
        pins = qualification(binary, dsn, root, common, frozen, output)
        assert pins["strategy_fingerprint"] == frozen["freeze"]["strategy_fingerprint"]
    executable = Path(case["selected"])
    selected_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    rules_armed, at_rules, release_rules = threading.Event(), threading.Event(), threading.Event()

    def hold_rules() -> None:
        if rules_armed.is_set():
            at_rules.set()
            if not release_rules.wait(timeout=9):
                raise ValueError("CONTROLLED_PREPARATION_CANCEL_NOT_OBSERVED")

    worker_exit = owner_fault in (
        "worker-exit", "worker-exit-before-claim", "worker-exit-during-execution",
        "worker-exit-after-candidate", "worker-exit-during-insert",
    )
    stale_worker = owner_fault in ("expiry-before-finalization", "expiry-before-recovery-publication")
    before_btc_rules = hold_rules if owner_fault == "recover-cancel" else None
    with backtest_market_input(output, before_btc_rules) as (ca, external):
        data = root.parent
        # 受控 HTTPS 行情前置：整段是真实网络 + ClickHouse/PG 写入，必须是独立可归因窗口。
        stage("prior-market-source-begin")
        source = probe(
            executable,
            database,
            "retained-source-prerequisite",
            fixture_capture_id=str(uuid4()),
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
        stage("prior-market-source-end")
        assert not (data / "backtest").exists()
        (data / "secrets").mkdir(mode=0o700)
        key = data / "secrets/dev-master-key"
        key.write_bytes(os.urandom(32))
        key.chmod(0o600)
        if web_assets is None:
            stage("web-build-begin")
            web_assets = build_web_assets(output)
            stage("web-build-end")
        generation = common["runtime_generation"]
        # Startup reads its configured release's Runtime root. Keep the real
        # Generation directory and all original artifacts in their existing home.
        assert Path(common["runtime_root"]) == data / "runtime"
        configuration = {
            "schema_version": 1,
            "user_data": str(data),
            "schema": str(ROOT / "database/postgres/migrations"),
            "assets": str(web_assets),
            "algorithms": common["algorithm_root"],
            "algorithm_artifact": common["algorithm_artifact"],
            "source_trust": str(ca),
            "postgres_peer": socket.gethostbyname("postgres") + ":5432",
            "clickhouse_database": database.config.database,
        }
        if publication is not None:
            from packages.backend.tests.application.test_strategy_research_evidence import (
                formal_strategy_freeze,
            )

            with original_host(executable, configuration, output) as freeze_http:
                command = str(uuid4())
                # 正式 Freeze POST（含其内部 GET 回来的 outcome）：阶段六的首个业务门槛窗口。
                stage("formal-freeze-post-begin")
                formal_freeze = formal_strategy_freeze(
                    freeze_http, publication["run_id"], publication["candidate_fingerprint"], command
                )
                stage("formal-freeze-post-end")
                (output / "formal-freeze.json").write_text(json.dumps(formal_freeze))
                assert formal_freeze["status"] == 200, formal_freeze
                view = formal_freeze["view"]
                for field in ("strategy_fingerprint", "freeze_relation_fingerprint"):
                    assert re.fullmatch(r"[0-9a-f]{64}", str(view.get(field))), formal_freeze
                assert view["command_id"] == command, formal_freeze
                # 正式响应体是 StrategyFreezeView：只有命令身份、策略/关联指纹、受理时间与
                # replayed；Run 与候选归属来自同一会话 GET 回来的 request，不来自响应体。
                assert view["replayed"] is False, formal_freeze
                outcome = formal_freeze["outcome"]
                assert outcome["state"] == "COMPLETED", formal_freeze
                assert outcome["request"] == {
                    "research_run_id": str(UUID(publication["run_id"])),
                    "candidate_fingerprint": publication["candidate_fingerprint"],
                    "comment": None,
                }, formal_freeze
                assert outcome["result"] == {**view, "replayed": True}, formal_freeze
                # 冻结关系的语义身份由生产 Freeze 写入；逐项核对它确实消费了本 Run 的 PG 发布：
                # 候选、执行证据集合必须等于 PG 侧证明的身份，等价性与准入摘要必须是独立身份。
                relation = view["freeze_relation_fingerprint"]
                manifests = [
                    json.loads(path.read_text())
                    for path in root.rglob("manifest.json")
                    if path.stat().st_size < 1 << 20
                ]
                matched = [m for m in manifests if m.get("relation_fingerprint") == relation]
                assert len(matched) == 1, {"relation": relation, "manifests": len(manifests)}
                binding = matched[0]
                assert binding["strategy_fingerprint"] == view["strategy_fingerprint"], binding
                assert binding["candidate_fingerprint"] == publication["candidate_fingerprint"], binding
                assert (
                    binding["research_execution_evidence_fingerprints"]
                    == publication["execution_evidence_fingerprints"]
                ), binding
                for field in ("admission_evidence_fingerprint", "research_result_fingerprint"):
                    assert re.fullmatch(r"[0-9a-f]{64}", str(binding.get(field))), binding
                equivalence = binding["equivalence_evidence_fingerprints"]
                assert equivalence and all(re.fullmatch(r"[0-9a-f]{64}", str(item)) for item in equivalence), binding
                assert binding["research_result_fingerprint"] != relation, binding
                subject = view["strategy_fingerprint"]
                strategy_path = f"/api/v2/strategies/{subject}"
                selection = {
                    "schema_version": 1,
                    "research_run_id": str(UUID(publication["run_id"])),
                    "freeze_relation_fingerprint": relation,
                    "policy_id": "experimental-backtest",
                    "policy_version": "1",
                }
                stage("qualification-post-begin")
                qualification_command = str(uuid4())
                qualified = request(freeze_http, f"{strategy_path}/qualifications", selection, qualification_command)
                stage("qualification-post-end")
                (output / "qualification.json").write_text(json.dumps(qualified))
                assert qualified["command_id"] == qualification_command, qualified
                assert qualified["state"] == "COMPLETED", qualified
                assert qualified["strategy_fingerprint"] == subject, qualified
                assert qualified["request"]["policy_id"] == selection["policy_id"], qualified
                assert qualified["request"]["policy_version"] == selection["policy_version"], qualified
                (evidence,) = qualified["request"]["evidence"]
                assert evidence["kind"] == "RESEARCH_RESULT", evidence
                assert evidence["evidence_fingerprint"] == binding["research_result_fingerprint"], evidence
                assert evidence["subject_binding_fingerprint"] == relation, evidence
                decision_id = qualified["decision_fingerprint"]
                assert re.fullmatch(r"[0-9a-f]{64}", decision_id), qualified
        warm_diagnostics = output / "backtest-producer.jsonl" if owner_fault is None else None
        with ExitStack() as warm_host:
            http = warm_host.enter_context(original_host(executable, configuration, output, diagnostics=warm_diagnostics))
            if publication is not None:
                assert request(http, f"{strategy_path}/qualifications/commands/{qualification_command}") == qualified
                stage("decision-cold-read-begin")
                decision = request(http, f"/api/v2/qualification-decisions/{decision_id}")
                stage("decision-cold-read-end")
                (output / "qualification-decision.json").write_text(json.dumps(decision))
                assert decision["state"] == "VERIFIED", decision
                assert decision["research_run_id"] == selection["research_run_id"], decision
                assert decision["decision_fingerprint"] == decision_id, decision
                assert decision["decision"]["evidence"] == [evidence], decision
                assert decision["decision"]["outcome"] == "APPROVED", decision
                promotion_command = str(uuid4())
                stage("promotion-post-begin")
                promoted = request(
                    http,
                    f"{strategy_path}/qualification-promotions",
                    {
                        **selection,
                        "qualification_decision_fingerprint": decision_id,
                        "reason": "Controlled current queue admission; experimental simulation only",
                    },
                    promotion_command,
                )
                stage("promotion-post-end")
                (output / "qualification-promotion.json").write_text(json.dumps(promoted))
                assert promoted["command_id"] == promotion_command, promoted
                assert promoted["state"] == "COMPLETED", promoted
                assert promoted["record"]["strategy_fingerprint"] == subject, promoted
                assert promoted["record"]["qualification_decision_fingerprint"] == decision_id, promoted
                assert promoted["record"]["to_stage"] == "BACKTEST", promoted
                pins = {
                    "strategy_fingerprint": subject,
                    "freeze_relation_fingerprint": relation,
                    "qualification_decision_fingerprint": decision_id,
                    "promotion_fingerprint": promoted["record"]["record_fingerprint"],
                }
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
            if owner_fault == "sim-start-refusals":
                from functools import partial

                from packages.backend.tests.transport.sim_start_product import exercise_sim_subjects, operator_inputs

                broker, operator_run = operator_inputs(http, payload)
                warm_host.close()
                exercise_sim_subjects(partial(original_host, executable, configuration, output), data / "secrets",
                                      payload, broker, operator_run, dsn)
                return
            if owner_fault == "human-owner-isolation":
                from packages.backend.tests.application.backtest_human_owners import (
                    assert_single_human_session,
                    exercise_human_owners,
                )

                assert_single_human_session(http)
                preflight, _ = prepare_comparison(http, payload)
                warm_host.close()
                exercise_human_owners(executable, configuration, output, payload, pins, selected_sha, dsn, preflight)
                return
            if owner_fault == "recover-cancel":
                rules_armed.set()
                assert_cancel_during_preparation(
                    http, dsn, {**payload, "backtest_command_id": str(uuid4())}, at_rules, release_rules
                )
            stage("preparation-post-begin")
            if owner_fault == "queued-cancel":
                accepted = accept_with_concurrent_read(http, dsn, preparation, payload)
            else:
                accepted = request(http, "/api/v2/backtest/preparations", payload, preparation)
            assert accepted["command_id"] == preparation and accepted["backtest_command_id"] == future
            assert accepted["run_id"] is None
            ready = observe_until(
                http,
                f"/api/v2/backtest/preparations/commands/{preparation}",
                {"READY"},
                {"ACCEPTED", "RUNNING", "INPUT_PENDING"},
            )
            stage("preparation-ready-end")
            assert ready["run_id"] is None and ready["backtest_outcome"] == "NOT_SUBMITTED"
            with psycopg.connect(dsn) as db:
                if owner_fault == "crash-recover":
                    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (preparation,))
                    committed = request(http, f"/api/v2/backtest/preparations/commands/{preparation}")
                    assert committed == ready, committed
                    db.rollback()
                assert db.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
                assert db.execute(
                    "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (future,)
                ).fetchone() == (0,)
            if owner_fault is not None:
                fresh = None
                if worker_exit or stale_worker or owner_fault in ("windows", "lost-guard", "crash-recover"):
                    fresh = prepare_comparison(http, payload)
            else:
                stage("run-submit-begin")
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
                assert run == ready["reserved_run_id"]
                stage("run-submit-end")
                # 真实执行窗口：从 submit 受理可见到 Run 终态可见，只包含正式观测循环。
                stage("run-execution-begin")
                completed = observe_until(http, f"/api/v2/backtest/runs/{run}", {"COMPLETED"}, {"QUEUED", "RUNNING"})
                stage("run-execution-end")
                assert completed["preparation_command_id"] == preparation
                stage("run-result-read-begin")
                result, _, _ = read_backtest_publication(http, run, preparation, pins, selected_sha)
                stage("run-result-read-end")
                stage("evidence-reads-begin")
                with psycopg.connect(dsn) as db:
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
                stage("evidence-reads-end")
        if worker_exit:
            with psycopg.connect(dsn) as db:
                existing_runs = {run for (run,) in db.execute("SELECT run_id::text FROM public.backtest_run")}
        if owner_fault is not None:
            # original_host has positively drained its own Running/Authority
            # before the next process opens the same physical owning resource.
            run = ready["reserved_run_id"]
            owner_scenario(
                binary, dsn, root, configuration, preparation, run, fresh, owner_fault, output
            )
        if worker_exit:
            queued = owner_fault == "worker-exit-before-claim"
            before, attempts, publications, members = publication_identity(dsn, run)
            state = "QUEUED" if queued else "RUNNING"
            assert before[0] == state and before[3:6] == (None, None, None), before
            assert not publications and not members
            assert [(attempt[1], attempt[2]) for attempt in attempts] == ([] if queued else [(1, "ACTIVE")])
            acceptance = backtest_acceptance(dsn, run, future)
            expected_before = [1] if owner_fault in (
                "worker-exit-during-execution", "worker-exit-after-candidate", "worker-exit-during-insert"
            ) else []
            if owner_fault in ("worker-exit", "worker-exit-during-execution"):
                before_events = run_diagnostics(output / f"owner-{owner_fault}.jsonl", run)
                assert execution_attempts(before_events) == expected_before, before_events
            if owner_fault == "worker-exit-during-insert":
                with psycopg.connect(dsn) as db:
                    expired = db.execute(
                        "UPDATE public.backtest_run_attempt SET lease_expires_at=last_heartbeat_at "
                        "WHERE run_id=%s AND attempt_id=%s AND state='ACTIVE' RETURNING attempt_id",
                        (run, attempts[0][0]),
                    ).fetchall()
                    assert expired == [(attempts[0][0],)], expired
            diagnostics = output / "backtest-worker-exit-recovery.jsonl"
            stage("worker-exit-recovery-begin")
            with original_host(executable, configuration, output, diagnostics=diagnostics) as http:
                completed = observe_until(
                    http, f"/api/v2/backtest/runs/{run}", {"COMPLETED"}, {"QUEUED", "RUNNING"}
                )
                assert completed["run_id"] == run and completed["preparation_command_id"] == preparation
                history = request(http, f"/api/v2/backtest/preparations/commands/{preparation}")
                assert history["run_id"] == run and history["backtest_command_id"] == future
                assert history["preparation_fingerprint"] == ready["preparation_fingerprint"]
                comparison_preparation, comparison_run = fresh
                run_comparison(http, comparison_preparation, comparison_run)
            after, recovered_attempts, _, _ = publication_identity(dsn, run)
            assert after[6:8] == before[6:8], (before, after)
            assert backtest_acceptance(dsn, run, future) == acceptance
            if queued:
                assert [attempt[1:3] for attempt in recovered_attempts] == [(1, "SUCCEEDED")], recovered_attempts
            else:
                first, second = recovered_attempts
                assert first == (*attempts[0][:2], "EXPIRED", *attempts[0][3:]), recovered_attempts
                assert second[4] != first[4], recovered_attempts
                with psycopg.connect(dsn) as db:
                    order = db.execute(
                        "SELECT first.lease_expires_at <= first.finished_at AND first.finished_at <= second.claimed_at "
                        "FROM public.backtest_run_attempt first JOIN public.backtest_run_attempt second USING (run_id) "
                        "WHERE first.run_id=%s AND first.attempt_number=1 AND second.attempt_number=2",
                        (run,),
                    ).fetchall()
                assert order == [(True,)], order
            assert execution_attempts(run_diagnostics(diagnostics, run)) == ([1] if queued else [2])
            assert execution_attempts(run_diagnostics(diagnostics, comparison_run)) == [1]
            stage("worker-exit-recovery-end")
        if owner_fault in ("queued-cancel", "running-cancel", "recover-cancel"):
            assert_cold_cancelled_backtest(executable, configuration, output, dsn, run, preparation, owner_fault)
        if owner_fault in ("missing-program", "missing-market-seal", "missing-market-row"):
            assert_missing_frozen_backtest_input(
                executable, configuration, output, dsn, run, preparation, owner_fault, database
            )
        if owner_fault == "attempts-exhausted":
            assert_backtest_attempts_exhausted(executable, configuration, output, dsn, run, preparation, future)
        if owner_fault == "lost-guard":
            row, attempts, publications, members = publication_identity(dsn, run)
            assert row[0] == "RUNNING" and row[3:6] == (None, None, None), row
            assert [(number, state) for _, number, state, _, _ in attempts] == [(1, "ACTIVE")], attempts
            assert not publications and not members
        if worker_exit or stale_worker or owner_fault in (None, "finite-publication", "shutdown-resume", "crash-recover"):
            run = ready["reserved_run_id"]
            recovered = stale_worker or owner_fault == "shutdown-resume" or (
                worker_exit and owner_fault != "worker-exit-before-claim"
            )
            production_count = f" producer_executions={len(expected_before) + 1}" if worker_exit else ""
            if owner_fault != "crash-recover" and not worker_exit:
                diagnostics = warm_diagnostics or output / f"owner-{owner_fault}.jsonl"
                executions = execution_attempts(run_diagnostics(diagnostics, run))
                expected_executions = [1, 2] if stale_worker else ([2] if recovered else [1])
                assert sorted(executions) == expected_executions, (run, executions)
                production_count = f" producer_executions={len(executions)}"
            stage("cold-publication-reads-begin")
            cold, recovered_artifacts = assert_cold_backtest_publication(
                executable,
                configuration,
                output,
                dsn,
                run,
                preparation,
                pins,
                selected_sha,
                attempt_states=("EXPIRED", "SUCCEEDED") if recovered else ("SUCCEEDED",),
                late_cancel=owner_fault == "crash-recover",
            )
            stage("cold-publication-reads-end")
            if owner_fault is None:
                assert cold == result
            (output / "actual-native-result.json").write_text(json.dumps(cold))
            print(f"BACKTEST_COLD_PUBLICATION_CONFIRMED run={run}{production_count} query_executions=0", flush=True)
        if worker_exit or stale_worker or owner_fault == "crash-recover":
            assert fresh is not None
            comparison_preparation, comparison_run = fresh
            recovered_comparison = owner_fault == "crash-recover"
            comparison, comparison_artifacts = assert_cold_backtest_publication(
                executable,
                configuration,
                output,
                dsn,
                comparison_run,
                comparison_preparation,
                pins,
                selected_sha,
                attempt_states=("EXPIRED", "SUCCEEDED") if recovered_comparison else ("SUCCEEDED",),
                late_cancel=recovered_comparison,
                prior_cancel=recovered_comparison,
                check_refusals=recovered_comparison,
            )
            if not recovered_comparison:
                assert_equivalent_publications(recovered_artifacts, comparison_artifacts, preparation, comparison_preparation)
            for field in ("metrics", "baseline", "curve", "positions"):
                assert comparison[field] == cold[field], field
            for trade, control_trade in zip(comparison["trades"], cold["trades"], strict=True):
                for field in ("ordinal", "time_ns", "side", "quantity", "price", "fee", "signal_time_ns"):
                    assert trade[field] == control_trade[field], field
            if worker_exit:
                with psycopg.connect(dsn) as db:
                    current_runs = {run for (run,) in db.execute("SELECT run_id::text FROM public.backtest_run")}
                new_runs = {run, comparison_run}
                assert existing_runs.isdisjoint(new_runs) and current_runs == existing_runs | new_runs
            if recovered_comparison:
                print(
                    f"BACKTEST_UNKNOWN_COMMITS_RESOLVED run={comparison_run} producer_executions=2 query_executions=0",
                    flush=True,
                )
        if owner_fault in ("crash-recover", "shutdown-resume"):
            baseline_diagnostics = output / "backtest-uninterrupted-producer.jsonl"
            with original_host(executable, configuration, output, diagnostics=baseline_diagnostics) as http:
                baseline_preparation, baseline_run = prepare_comparison(http, payload)
                run_comparison(http, baseline_preparation, baseline_run)
            assert execution_attempts(run_diagnostics(baseline_diagnostics, baseline_run)) == [1]
            _, baseline_artifacts = assert_cold_backtest_publication(
                executable, configuration, output, dsn, baseline_run, baseline_preparation, pins, selected_sha
            )
            expected_runs = {run, baseline_run}
            assert_equivalent_publications(recovered_artifacts, baseline_artifacts, preparation, baseline_preparation)
            if owner_fault == "crash-recover":
                expected_runs.add(comparison_run)
                assert_equivalent_publications(
                    comparison_artifacts, baseline_artifacts, comparison_preparation, baseline_preparation
                )
            with psycopg.connect(dsn) as db:
                assert {r for (r,) in db.execute("SELECT run_id::text FROM public.backtest_run")} == expected_runs
            print(f"BACKTEST_UNINTERRUPTED_COMPARISON_CONFIRMED run={run} baseline={baseline_run}", flush=True)


@contextmanager
def backtest_market_input(output: Path, before_btc_rules: Callable[[], None] | None) -> Iterator[tuple[Path, dict[str, Any]]]:
    from scripts.native_web_e2e import controlled_source_https

    with controlled_source_https(output, before_btc_rules=before_btc_rules) as market:
        yield market
        occurrences = [json.loads(line) for line in (output / "controlled-source-https.jsonl").read_text().splitlines()]
        assert any(row.get("path") == "/api/v3/exchangeInfo" and row.get("status") == 200 for row in occurrences), (
            occurrences
        )
    # 受控 HTTPS 前置已退出，原生链路的全部真实边界到此收口；快照同时落盘。
    stage("native-chain-end")
    dump_stages("native-chain")
