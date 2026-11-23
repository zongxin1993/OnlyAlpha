"""单次 Web 诊断的只读协调探针；不提交命令，不产生 CompletionProof。"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.observation_report import FIELDS

CONTROL_OPERATIONS = frozenset(
    {
        "generation.hold",
        "generation.lock_attempt",
        "backtest.run_one",
        "backtest.finalize",
        "backtest.terminal.cleanup",
        "http.backtest.get",
        "http.handler",
        "http.ingress.dispatch",
        "http.response.body",
        "http.socket.write",
        "http.socket.flush",
        "http.socket.shutdown",
    }
)


def read_control_events(path: Path, cursor: int):
    """每次只读新增完整行；大量 Source 子阶段留在原日志，避免反复全量解析。"""
    if type(cursor) is not int or cursor < 0:
        raise ValueError("DIAGNOSTIC_CURSOR_INVALID")
    if not path.exists():
        if cursor:
            raise ValueError("DIAGNOSTIC_CURSOR_INVALID")
        return {"cursor": 0, "events": []}
    events = []
    with path.open("rb") as stream:
        if cursor > os.fstat(stream.fileno()).st_size:
            raise ValueError("DIAGNOSTIC_CURSOR_INVALID")
        stream.seek(cursor)
        end = cursor
        while stream.tell() - cursor < 4 * 1024 * 1024:
            line = stream.readline(16385)
            if not line:
                break
            if len(line) > 16384:
                raise ValueError("DIAGNOSTIC_EVENT_INVALID")
            if not line.endswith(b"\n"):
                break
            try:
                row = json.loads(line)
                if (
                    not isinstance(row, dict)
                    or set(row) - FIELDS
                    or type(row.get("schema_version")) is not int
                    or row["schema_version"] != 1
                ):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise ValueError("DIAGNOSTIC_EVENT_INVALID") from None
            if row.get("operation") in CONTROL_OPERATIONS or row.get("event_kind") in {
                "session_start",
                "session_end",
                "diagnostic_loss",
            }:
                events.append(row)
            end = stream.tell()
    return {"cursor": end, "events": events}


def observe_sql(connection, run, namespace):
    binding = connection.execute(
        "SELECT semantic_store_id::text FROM public.research_deployment_semantic_store_binding WHERE singleton=TRUE"
    ).fetchone()
    if binding != (namespace,):
        raise ValueError("DIAGNOSTIC_NAMESPACE_MISMATCH")
    row = connection.execute(
        "SELECT state,finished_at IS NOT NULL,admission_resolution_payload::jsonb->>'semantic_store_id' FROM public.backtest_run WHERE run_id=%s::uuid",
        (run,),
    ).fetchone()
    if row is None:
        return {"state": "unknown", "reason": "original_run_not_observed"}
    if row[2] != namespace:
        raise ValueError("DIAGNOSTIC_NAMESPACE_MISMATCH")
    if (
        row[0] not in {"QUEUED", "RUNNING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELLED"}
        or type(row[1]) is not bool
    ):
        raise ValueError("DIAGNOSTIC_SQL_STATE_INVALID")
    return {"state": row[0], "finished": row[1]}


def validate_selection(args):
    if not getattr(args, "backtest_diagnostic", False):
        return
    if not (
        args.backtest_market_input
        and args.controlled_source_https
        and args.retained_market_input
        and not args.contract_fuzz
        and not args.restart_check
        and args.grep is None
        and args.tests == ["e2e/backtest-diagnostics.spec.ts"]
    ):
        raise ValueError("BACKTEST_DIAGNOSTIC_SELECTION_INVALID")


def _stop_browser_group(child):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def run_browser(command, *, cwd, env, receipt):
    """为原20秒Host排空留余量；只终止自己创建的浏览器进程组。"""
    started = time.monotonic()
    exhausted = False
    interrupted = False
    result = None
    child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        result = child.wait(timeout=1160)
    except subprocess.TimeoutExpired:
        exhausted = True
        _stop_browser_group(child)
        result = 124
    except BaseException:
        interrupted = True
        _stop_browser_group(child)
        raise
    finally:
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "browser_budget_seconds": 1160,
                    "host_drain_budget_seconds": 20,
                    "overall_budget_seconds": 1200,
                    "budget_exhausted": exhausted,
                    "interrupted": interrupted,
                    "elapsed_seconds": time.monotonic() - started,
                    "pid": child.pid,
                    "returncode": result,
                },
                indent=2,
            )
            + "\n"
        )
    return result


def finish_capture(events, close, expected_pid, browser_result, output):
    """排空后认证诊断流，不认证业务完成；关闭缺证必须否决浏览器的零退出。"""
    from scripts.observation_report import load_observation_files

    result = dict(schema_version=1, complete=False, stream_complete=False, browser_returncode=browser_result)
    try:
        receipts = [json.loads(line) for line in close.read_text().splitlines() if line.strip()]
        starts = []
        last_mono = 0
        for line in events.read_text().splitlines():
            row = json.loads(line)
            if type(row.get("mono_ns")) is not int or row["mono_ns"] < 0:
                raise ValueError("event clock")
            last_mono = max(last_mono, row["mono_ns"])
            if row.get("event_kind") == "session_start":
                starts.append(row)
        if len(receipts) != 1 or len(starts) != 1:
            raise ValueError("session count")
        receipt, start = receipts[0], starts[0]
        if (
            receipt.get("schema_version") != 1
            or type(receipt.get("schema_version")) is not int
            or receipt.get("event_kind") != "session_end"
            or type(receipt.get("pid")) is not int
            or receipt["pid"] != expected_pid
            or start.get("pid") != expected_pid
            or not isinstance(receipt.get("process_instance_id"), str)
            or not receipt["process_instance_id"]
            or receipt["process_instance_id"] != start.get("process_instance_id")
            or receipt.get("shutdown_complete") is not True
            or type(receipt.get("mono_ns")) is not int
            or receipt["mono_ns"] < last_mono
            or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in ("dropped_events", "io_errors"))
        ):
            raise ValueError("session identity or close")
        report = load_observation_files([events, close])
        result["stream_complete"] = report["complete"] and all(
            row.get("pid") == expected_pid and row["process_instance_id"] == receipt["process_instance_id"]
            for row in report["operations"]
        )
        result["complete"] = result["stream_complete"] and browser_result == 0
        result["reason"] = "complete" if result["complete"] else "diagnostic_stream_or_browser_incomplete"
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        result["reason"] = "DIAGNOSTIC_CAPTURE_INVALID"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return browser_result or (0 if result["complete"] else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--cursor", type=int, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--sql", action="store_true")
    args = parser.parse_args()
    for value in (args.run, args.namespace):
        identity = uuid.UUID(value)
        if identity.version != 4 or str(identity) != value:
            raise ValueError("DIAGNOSTIC_IDENTITY_INVALID")
    result = read_control_events(args.events, args.cursor)
    result["available_bytes"] = args.events.stat().st_size if args.events.exists() else 0
    if args.sql:
        import psycopg

        from scripts.database_guard import assert_test_database

        dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
        assert_test_database(dsn)
        with psycopg.connect(
            dsn, options="-c default_transaction_read_only=on -c statement_timeout=1000", connect_timeout=3
        ) as connection:
            result["sql"] = observe_sql(connection, args.run, args.namespace)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("BACKTEST_DIAGNOSTIC_PROBE_FAILED", file=sys.stderr)
        raise SystemExit(1) from None
