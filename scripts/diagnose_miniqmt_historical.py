"""Run an opt-in MiniQMT historical compatibility matrix with process isolation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_plugin_miniqmt.historical_worker.models import OnlyMiniQmtWorkerRequest
from onlyalpha_plugin_miniqmt.historical_worker.protocol import atomic_write_json, read_json, tail


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    period: str = "1m"
    count: int = 50
    query_mode: str = "END_TIME_WITH_COUNT"
    download: bool = True
    fields: tuple[str, ...] = ("time", "open", "high", "low", "close", "volume")
    fill_data: bool = False


CASES = (
    Case("stage1-range", query_mode="TIME_RANGE"),
    Case("stage1-end-count"),
    Case("stage1-count-only", query_mode="COUNT_ONLY"),
    *(Case(f"stage2-count-{count}", count=count) for count in (1, 10, 50, 100, 200)),
    Case("stage2-period-5m", period="5m"),
    Case("stage2-period-1d", period="1d"),
    Case("stage3-no-download", download=False),
    Case("stage3-default-fields", fields=()),
    Case("stage4-fill-data", fill_data=True),
)


def _run_case(case: Case, args: argparse.Namespace, end: datetime) -> dict[str, object]:
    workdir = args.output / case.case_id
    workdir.mkdir(parents=True, exist_ok=False)
    end_text = end.astimezone(UTC).isoformat().replace("+00:00", "Z")
    request = OnlyMiniQmtWorkerRequest(
        case.case_id,
        str(args.userdata_mini.resolve()),
        args.instrument,
        args.symbol,
        case.period,
        case.count,
        end_text,
        int(end.timestamp()) * 1_000_000_000 + end.microsecond * 1_000,
        case.fields,
        "none",
        case.fill_data,
        args.price_precision,
        args.quantity_precision,
        f"diagnostic-{case.case_id}",
        case.query_mode,
        case.download,
        10,
        max(200, case.count + 10),
    )
    request_path = workdir / "request.json"
    atomic_write_json(request_path, request.payload())
    stdout_path, stderr_path = workdir / "stdout.log", workdir / "stderr.log"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            (
                sys.executable,
                "-m",
                "onlyalpha_plugin_miniqmt.historical_worker.worker",
                "--request",
                str(request_path),
            ),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=workdir,
        )
        try:
            exit_code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            return _case_result(case, "TIMEOUT", process.returncode, stdout_path, stderr_path)
    result_path, failure_path = workdir / "result.json", workdir / "failure.json"
    if exit_code == 0 and result_path.is_file():
        manifest = read_json(result_path)
        return {
            **_case_result(case, "PASS", exit_code, stdout_path, stderr_path),
            "row_count": manifest.get("row_count"),
            "content_fingerprint": manifest.get("content_fingerprint"),
            "provider_version": manifest.get("provider_version"),
        }
    if failure_path.is_file():
        failure = read_json(failure_path)
        status = (
            "EMPTY_DATA"
            if failure.get("status") == "EMPTY_RESULT"
            else "INVALID_DATA"
            if failure.get("status") == "INVALID_DATA"
            else "PYTHON_EXCEPTION"
        )
        return {**_case_result(case, status, exit_code, stdout_path, stderr_path), "failure": failure}
    return _case_result(case, "PROCESS_ABORT", exit_code, stdout_path, stderr_path)


def _case_result(
    case: Case,
    status: str,
    exit_code: int | None,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "status": status,
        "worker_exit_code": exit_code,
        "stdout_tail": tail(stdout_path),
        "stderr_tail": tail(stderr_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--userdata-mini", type=Path, required=True)
    parser.add_argument("--symbol", default="600000.SH")
    parser.add_argument("--instrument", default="600000.XSHG")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-time", default=datetime.now(UTC).replace(second=0, microsecond=0).isoformat())
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--price-precision", type=int, default=2)
    parser.add_argument("--quantity-precision", type=int, default=0)
    args = parser.parse_args()
    if not args.userdata_mini.is_dir():
        parser.error(f"userdata_mini does not exist: {args.userdata_mini}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    end = datetime.fromisoformat(args.end_time).astimezone(UTC)
    cases = [_run_case(case, args, end) for case in CASES]
    report = {
        "environment": {
            "userdata_mini_path": str(args.userdata_mini.resolve()),
            "python_version": sys.version,
            "symbol": args.symbol,
        },
        "cases": cases,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(args.output / "report.json"), "cases": len(cases)}))
    return 0 if any(case["status"] == "PASS" for case in cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
