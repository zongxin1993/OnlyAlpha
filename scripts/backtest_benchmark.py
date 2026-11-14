"""汇总回测模块基准、发布分段计时和 Playwright 请求；不修改门禁。"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit


def distribution(values: list[int | float]) -> dict:
    ordered = sorted(values)
    return {
        "calls": len(values),
        "total_ns": sum(values),
        "median_ns": statistics.median(values),
        "p95_ns": ordered[math.ceil(len(values) * 0.95) - 1],
    }


def profile(lines: list[str]) -> dict:
    spans = {}
    errors = []
    samples = defaultdict(list)
    meta = []
    sample_records = []
    for line in lines:
        if line.startswith("BACKTEST_PROFILE "):
            event = json.loads(line.partition(" ")[2])
            key = (event["pid"], event.get("id"))
            if event["event"] == "begin":
                if key in spans:
                    raise ValueError("duplicate span identity")
                spans[key] = {**event, "children_ns": 0}
            elif event["event"] == "end":
                if key not in spans or "elapsed_ns" in spans[key]:
                    raise ValueError("unmatched span end")
                spans[key].update(elapsed_ns=int(event["elapsed_ns"]), ok=event["ok"])
            else:
                errors.append(event)
        elif line.startswith("BACKTEST_BENCHMARK "):
            row = json.loads(line.partition(" ")[2])
            samples[row["stage"]].append(int(row["elapsed_ns"]))
            sample_records.append(row)
        elif line.startswith("BACKTEST_BENCHMARK_META "):
            meta.append(json.loads(line.partition(" ")[2]))
    incomplete_parents = set()
    for row in spans.values():
        if "elapsed_ns" not in row:
            parent_id = row["parent"]
            seen = {row["id"]}
            while parent_id is not None:
                if parent_id in seen:
                    raise ValueError("cyclic parent span")
                seen.add(parent_id)
                parent_key = (row["pid"], parent_id)
                incomplete_parents.add(parent_key)
                parent_row = spans.get(parent_key)
                parent_id = parent_row["parent"] if parent_row else None
        if "elapsed_ns" in row and row["parent"] is not None:
            parent = spans.get((row["pid"], row["parent"]))
            if parent is None:
                raise ValueError("missing parent span")
            parent["children_ns"] += row["elapsed_ns"]
    groups = defaultdict(list)
    incomplete = []
    for row in spans.values():
        if "elapsed_ns" not in row or (row["pid"], row["id"]) in incomplete_parents:
            incomplete.append(row)
            continue
        exclusive = row["elapsed_ns"] - row["children_ns"]
        if exclusive < 0:
            raise ValueError("child duration exceeds parent duration")
        row["exclusive_ns"] = exclusive
        groups[(row["run"], row["stage"], row["ok"])].append(row)
    return {
        "schema_version": 1,
        "metadata": meta,
        "samples": sample_records,
        "benchmarks": {key: distribution(value) for key, value in sorted(samples.items())},
        "stages": [
            {
                "run": run,
                "stage": stage,
                "ok": ok,
                "inclusive": distribution([r["elapsed_ns"] for r in rows]),
                "exclusive": distribution([r["exclusive_ns"] for r in rows]),
            }
            for (run, stage, ok), rows in sorted(groups.items())
        ],
        "incomplete": incomplete,
        "diagnostics": errors,
    }


def requests(path: Path) -> list[dict]:
    rows = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".network"):
                continue
            for line in archive.read(name).splitlines():
                snapshot = json.loads(line).get("snapshot", {})
                request = snapshot.get("request", {})
                url = urlsplit(request.get("url", ""))
                if not url.path.startswith("/api/"):
                    continue
                response = snapshot.get("response", {})
                row = {
                    "at": snapshot.get("startedDateTime"),
                    "method": request.get("method"),
                    "path": url.path,
                    "status": response.get("status"),
                    "elapsed_ms": snapshot.get("time"),
                }
                # 只摘出流程状态/错误码，避免复制凭据、查询参数及用户策略正文。
                body = response.get("content", {}).get("_sha1")
                if body and "/backtest/" in url.path:
                    try:
                        value = json.loads(archive.read("resources/" + body))
                    except (KeyError, ValueError):
                        value = {}
                    if isinstance(value, dict):
                        row["state"] = value.get("state")
                        row["phase"] = value.get("phase")
                        detail = value.get("detail") or value.get("error") or {}
                        if isinstance(detail, dict):
                            row["code"] = detail.get("code")
                rows.append(row)
    return rows


def require_complete(report: dict) -> None:
    metadata = report["metadata"][0]
    rounds = metadata.get("rounds")
    stage_count = metadata.get("stage_count")
    if not isinstance(rounds, int) or not isinstance(stage_count, int) or rounds < 1 or stage_count < 1:
        raise ValueError("missing benchmark round/stage count")
    for key in ("benchmark_binary_sha256", "compiler", "os", "arch"):
        if not metadata.get(key):
            raise ValueError(f"missing benchmark build identity: {key}")
    groups = defaultdict(list)
    for row in report.get("samples", []):
        groups[row["round"]].append(row)
    if set(groups) != set(range(1, rounds + 1)):
        raise ValueError("incomplete benchmark rounds")
    expected = None
    for rows in groups.values():
        stages = {row["stage"] for row in rows}
        if len(rows) != stage_count or len(stages) != stage_count or "chain.total" not in stages:
            raise ValueError("incomplete or duplicate benchmark stages")
        if expected is not None and stages != expected:
            raise ValueError("inconsistent benchmark stages")
        if not next(row for row in rows if row["stage"] == "chain.total").get("result_sha256"):
            raise ValueError("missing benchmark result identity")
        expected = stages


def compare(current: dict, baseline: dict) -> dict:
    if len(current["metadata"]) != 1 or len(baseline["metadata"]) != 1:
        raise ValueError("comparison requires exactly one benchmark metadata record per report")
    require_complete(current)
    require_complete(baseline)
    for key in (
        "stage_count",
        "scope",
        "profile",
        "compiler",
        "os",
        "arch",
        "storage",
        "trace_sha256",
        "configuration_sha256",
        "input_pin",
        "bars",
        "cache",
    ):
        if key not in current["metadata"][0] or key not in baseline["metadata"][0]:
            raise ValueError(f"missing benchmark metadata: {key}")
        if current["metadata"][0][key] != baseline["metadata"][0][key]:
            raise ValueError(f"incomparable benchmark metadata: {key}")
    if set(current["benchmarks"]) != set(baseline["benchmarks"]):
        raise ValueError("incomparable benchmark stages")

    def results(report: dict) -> set[str]:
        return {
            row["result_sha256"]
            for row in report.get("samples", [])
            if row["stage"] == "chain.total" and row.get("result_sha256")
        }

    if len(results(current)) != 1 or results(current) != results(baseline):
        raise ValueError("missing or changed benchmark result identity")
    return {
        stage: {
            "current_median_ns": row["median_ns"],
            "baseline_median_ns": baseline["benchmarks"][stage]["median_ns"],
            "ratio": row["median_ns"] / baseline["benchmarks"][stage]["median_ns"],
        }
        for stage, row in current["benchmarks"].items()
        if stage in baseline["benchmarks"] and baseline["benchmarks"][stage]["median_ns"] > 0
    }


def module_reports(paths: list[Path]) -> list[dict]:
    from scripts.rust_benchmark import compare_report_sets

    rows = []
    for path in paths:
        value = json.loads(path.read_text())
        if not isinstance(value, list):
            raise ValueError("module benchmark report must be a case array")
        rows.extend(value)
    if rows:
        compare_report_sets(rows, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", type=Path, default=[])
    parser.add_argument("--trace", action="append", type=Path, default=[])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--module-report", action="append", type=Path, default=[])
    parser.add_argument("--module-baseline", action="append", type=Path, default=[])
    parser.add_argument("--observations", action="append", type=Path, default=[], help="v1 JSONL与独立关闭收据")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = profile([line for path in args.log for line in path.read_text().splitlines()])
    report["requests"] = [{"trace": str(path), "requests": requests(path)} for path in args.trace]
    report["module_benchmarks"] = module_reports(args.module_report)
    if args.observations:
        from scripts.observation_report import flow_summary, load_observation_files

        report["observations"] = load_observation_files(args.observations)
        groups = {}
        for row in report["observations"]["operations"]:
            if row.get("run_id"):
                groups.setdefault(row["run_id"], []).append(row)
        report["observations"]["runs"] = {
            run: flow_summary({**report["observations"], "operations": rows}, run) for run, rows in groups.items()
        }
    if args.log:
        from scripts.observation_report import legacy_observation_report

        report["legacy_observations"] = legacy_observation_report(
            [line for path in args.log for line in path.read_text().splitlines()]
        )
    if args.module_baseline:
        from scripts.rust_benchmark import compare_report_sets

        report["module_comparison"] = compare_report_sets(
            report["module_benchmarks"], module_reports(args.module_baseline)
        )
    if args.baseline:
        report["comparison"] = compare(report, json.loads(args.baseline.read_text()))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
