from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".test-metrics" / "worker-matrix.json"


def _git_commit() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=False, text=True
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        return "unknown"


def benchmark(args: argparse.Namespace) -> int:
    records: list[dict[str, object]] = []
    failed = False
    for lane in args.lanes:
        for worker in args.workers:
            for dist in args.dist:
                for run_number in range(1, args.repeat + 1):
                    metric_path = ROOT / ".test-metrics" / f"{lane}.json"
                    metric_path.unlink(missing_ok=True)
                    command = [
                        "uv",
                        "run",
                        "python",
                        "scripts/test_suite.py",
                        lane,
                        "--workers",
                        worker,
                        "--dist",
                        dist,
                    ]
                    print("> " + subprocess.list2cmdline(command), flush=True)
                    code = subprocess.run(command, cwd=ROOT, check=False).returncode
                    metrics = json.loads(metric_path.read_text(encoding="utf-8")) if metric_path.is_file() else {}
                    record = {
                        "lane": lane,
                        "worker": worker,
                        "dist": dist,
                        "run_number": run_number,
                        "collected": metrics.get("collected", 0),
                        "passed": metrics.get("passed", 0),
                        "failed": metrics.get("failed", 0),
                        "duration": metrics.get("total_seconds", 0.0),
                        "exit_code": code,
                        "cpu_count": os.cpu_count() or 0,
                        "os": platform.platform(),
                        "python_version": platform.python_version(),
                        "commit": _git_commit(),
                    }
                    records.append(record)
                    failed |= code != 0
                    _write_output(Path(args.output), records)
    _write_output(Path(args.output), records)
    return 1 if failed else 0


def _write_output(path: Path, records: list[dict[str, object]]) -> None:
    summaries: list[dict[str, object]] = []
    keys = sorted({(str(item["lane"]), str(item["worker"]), str(item["dist"])) for item in records})
    for lane, worker, dist in keys:
        selected = [item for item in records if (item["lane"], item["worker"], item["dist"]) == (lane, worker, dist)]
        durations = [float(item["duration"]) for item in selected if item["exit_code"] == 0]
        if not durations:
            continue
        ordered = sorted(durations)
        p95_index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
        median = statistics.median(durations)
        p95 = ordered[p95_index]
        summaries.append(
            {
                "lane": lane,
                "worker": worker,
                "dist": dist,
                "median_seconds": median,
                "p95_seconds": p95,
                "p95_p50_ratio": 0.0 if median == 0 else p95 / median,
                "failure_rate": sum(item["exit_code"] != 0 for item in selected) / len(selected),
                "runs": len(selected),
            }
        )
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "records": records,
        "summaries": summaries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark pytest lane worker/distribution combinations")
    parser.add_argument("--lanes", nargs="+", required=True)
    parser.add_argument("--workers", nargs="+", required=True)
    parser.add_argument("--dist", nargs="+", choices=("load", "loadscope", "loadfile", "worksteal"), required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    if args.repeat < 3:
        parser.error("--repeat must be at least 3")
    return benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
