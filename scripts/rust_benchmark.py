"""Rust 模块基准清单、结果校验和同条件比较；不改变性能门禁。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import posixpath
import re
import statistics
from pathlib import Path, PurePosixPath


def benchmark_input_identity(source_inputs: dict, case: dict) -> str:
    """Bind measured harness/helpers/data from the captured cut, not today's mutable files."""
    from scripts.rust_kernel_check import BENCHMARK_SOURCE_INPUTS

    area = "packages/backend" if case["crate"] == "backend" else "crates/" + case["crate"]
    harness = area + "/benches/" + case["target"] + ".rs"
    spec = BENCHMARK_SOURCE_INPUTS[harness]
    parent = PurePosixPath(harness).parent
    paths = {harness}
    paths.update(posixpath.normpath(str(parent / json.loads(path))) for path in spec["fixtures"])
    paths.update(posixpath.normpath(str(parent / path)) for path in spec["modules"])
    selected = {}
    for path in paths:
        value = source_inputs.get(path)
        if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
            raise ValueError("missing captured benchmark input: " + path)
        selected[path] = value
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def validate_fixture_provenance(directory: Path) -> None:
    files = json.loads((directory / "provenance.json").read_text())["files"]
    if not files:
        raise ValueError("missing fixture provenance")
    for name, expected in files.items():
        path = directory / name
        if Path(name).name != name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"fixture bytes differ: {name}")


def result_identity(log: str) -> str:
    rows = {}
    for line in log.splitlines():
        if line.startswith("BENCHMARK_RESULT "):
            _, case, value = line.split(" ", 2)
            if case in rows:
                raise ValueError("duplicate preflight result")
            rows[case] = value
    if not rows:
        raise ValueError("missing preflight results")
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def criterion_samples(data: dict) -> list[float]:
    """读取 Criterion 原始批次，归一为每次操作；统计推断仍由 Criterion 负责。"""
    counts, times = data.get("iters", []), data.get("times", [])
    if len(counts) < 3 or len(counts) != len(times):
        raise ValueError("incomplete Criterion samples")
    if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in [*counts, *times]):
        raise ValueError("invalid Criterion samples")
    return [elapsed / count for count, elapsed in zip(counts, times, strict=True)]


def storage_conditions(mountinfo: str, locations: dict[str, str]) -> dict:
    """按实际输入/临时目录选最长挂载点；排除 overlay 临时层 ID。"""

    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)

    mounts = []
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        left, right = before.split(), after.split()
        if not separator or len(left) < 6 or len(right) < 3:
            raise ValueError("invalid storage mount evidence")
        mounts.append((left, right))
    result = {}
    for role, location in locations.items():
        path = PurePosixPath(location)
        if not path.is_absolute():
            raise ValueError("storage location must be absolute")
        selected = [(left, right) for left, right in mounts if path.is_relative_to(unescape(left[4]))]
        if not selected:
            raise ValueError("missing storage mount evidence")
        left, right = max(selected, key=lambda row: len(unescape(row[0][4])))
        if sum(unescape(candidate[0][4]) == unescape(left[4]) for candidate in selected) != 1:
            raise ValueError("ambiguous storage mount evidence")
        result[role] = dict(
            mountpoint=unescape(left[4]),
            root=unescape(left[3]),
            filesystem=right[0],
            source=unescape(right[1]),
            mount_options=sorted(left[5].split(",")),
            filesystem_options=sorted(
                option
                for option in right[2].split(",")
                if option.split("=", 1)[0] not in {"lowerdir", "upperdir", "workdir"}
            ),
        )
    if not result:
        raise ValueError("missing storage locations")
    return dict(schema_version=1, locations=result)


def _module_report(metadata: dict, case: str, unit: str, count: int, samples: list, result: str) -> dict:
    report = dict(
        schema_version=1,
        case=f"{metadata['case']['crate']}/{metadata['case']['target']}/{case}",
        input_sha256=metadata["input_sha256"],
        result_sha256=result,
        environment={
            **{key: metadata[key] for key in ("compiler", "platform", "profile", "features", "cache", "hardware")},
            "storage": metadata.get("storage"),
            **(
                {"diagnostics_mode": metadata["diagnostics_mode"]}
                if metadata.get("diagnostics_mode", "off") != "off"
                else {}
            ),
        },
        build={key: metadata[key] for key in ("source", "binary_sha256")},
        unit=unit,
        work_items=count,
        samples_ns=samples,
    )
    if metadata.get("diagnostics_receipt") is not None:
        report["diagnostics_receipt"] = metadata["diagnostics_receipt"]
    return report


def criterion_reports(samples: list[dict], metadata: dict) -> list[dict]:
    if metadata["preflight"] != "passed all source assertions" or metadata["measurement"] != "complete":
        raise ValueError("incomplete benchmark")
    reports = []
    for sample in samples:
        case = sample["case"]
        throughput = case.get("throughput") or {}
        if len(throughput) != 1 or next(iter(throughput)) not in ("Bytes", "Elements"):
            raise ValueError("missing benchmark work unit")
        unit, count = next(iter(throughput.items()))
        if count <= 0:
            raise ValueError("invalid benchmark work count")
        report = _module_report(
            metadata,
            case["full_id"],
            "bytes" if unit == "Bytes" else "elements",
            count,
            sample["samples_ns"],
            metadata["result_sha256"],
        )
        report["criterion_estimates"] = sample["criterion_estimates"]
        report["measurement_engine"] = "criterion"
        reports.append(report)
    return reports


def diagnostic_receipt(log, expected_mode):
    rows = [line.partition(" ")[2] for line in log.splitlines() if line.startswith("BENCHMARK_DIAGNOSTICS ")]
    try:
        if len(rows) != 1:
            raise ValueError()
        row = json.loads(rows[0])
        receipt = row["receipt"]
        if (
            row.get("mode") != expected_mode
            or not isinstance(receipt, dict)
            or type(receipt.get("schema_version")) is not int
            or receipt["schema_version"] != 1
            or receipt.get("event_kind") != "session_end"
            or receipt.get("shutdown_complete") is not True
            or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in ("dropped_events", "io_errors"))
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("incomplete benchmark diagnostics") from None
    return receipt


def retained_reports(log: str, metadata: dict) -> list[dict]:
    case = metadata["case"]
    rounds = case["rounds"]
    stages = set(case["stages"])
    if not isinstance(rounds, int) or rounds < 3 or not stages:
        raise ValueError("incomplete fixed sample contract")
    samples = {}
    results = {}
    for line in log.splitlines():
        if line.startswith("BENCHMARK_SAMPLE "):
            row = json.loads(line.partition(" ")[2])
            key = (row["round"], row["stage"])
            if (
                row.get("schema_version") != 1
                or row["crate"] != "onlyalpha-" + case["crate"]
                or key in samples
                or row["stage"] not in stages
                or row["round"] not in range(1, rounds + 1)
            ):
                raise ValueError("duplicate or foreign fixed sample")
            elapsed = int(row["elapsed_ns"])
            if elapsed <= 0:
                raise ValueError("invalid fixed sample")
            samples[key] = elapsed
        elif line.startswith("BENCHMARK_RESULT "):
            _, number, value = line.split(" ", 2)
            number = int(number)
            if number in results or re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError("invalid fixed sample result")
            results[number] = value
    if (
        set(samples) != {(n, stage) for n in range(1, rounds + 1) for stage in stages}
        or set(results) != set(range(1, rounds + 1))
        or len(set(results.values())) != 1
    ):
        raise ValueError("incomplete or changed fixed sample result")
    reports = []
    for stage in sorted(stages):
        report = _module_report(
            metadata,
            stage,
            case.get("unit", "replay_entries"),
            case["sizes"][0],
            [samples[n, stage] for n in range(1, rounds + 1)],
            results[1],
        )
        report["measurement_engine"] = "fixed_samples"
        reports.append(report)
    return reports


def legacy_reports(log: str, metadata: dict) -> list[dict]:
    from scripts.backtest_benchmark import profile, require_complete

    data = profile(log.splitlines())
    if len(data["metadata"]) != 1:
        raise ValueError("ambiguous legacy benchmark metadata")
    require_complete(data)
    actual = data["metadata"][0]
    if actual["rounds"] < 3:
        raise ValueError("incomplete fixed sample rounds")
    if (
        actual["benchmark_binary_sha256"] != metadata["binary_sha256"]
        or actual["compiler"] != metadata["compiler"].splitlines()[0]
    ):
        raise ValueError("legacy benchmark binary does not match current executable receipt")
    results = {row["result_sha256"] for row in data["samples"] if row["stage"] == "chain.total"}
    if len(results) != 1:
        raise ValueError("changed legacy benchmark result")
    reports = []
    for stage in sorted(data["benchmarks"]):
        rows = sorted((row for row in data["samples"] if row["stage"] == stage), key=lambda row: row["round"])
        report = _module_report(
            metadata,
            stage,
            metadata["case"]["unit"],
            metadata["case"]["sizes"][0],
            [int(row["elapsed_ns"]) for row in rows],
            next(iter(results)),
        )
        report["measurement_engine"] = "fixed_samples"
        reports.append(report)
    return reports


def validate_complete_trace(path: Path, fixture: dict) -> str:
    """Preflight only: full trace integrity remains with TerminalSnapshot's exact verifier."""
    raw = path.read_bytes()
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or not {"binding", "inputs", "schema_version", "kind", "state", "steps"} <= value.keys()
    ):
        raise ValueError("backend benchmark requires original complete trace, not header extract")
    if value["binding"] != fixture["binding"] or value["inputs"] != fixture["inputs"]:
        raise ValueError("complete trace binding/input differs from controlled fixture")
    return hashlib.sha256(raw).hexdigest()


def validate_inventory(root: Path, cases: list[dict]) -> None:
    seen = set()
    for row in cases:
        key = (row["crate"], row["target"])
        if key in seen:
            raise ValueError(f"duplicate benchmark: {key}")
        seen.add(key)
        area = root / "packages/backend" if row["crate"] == "backend" else root / "crates" / row["crate"]
        source = area / "benches" / (row["target"] + ".rs")
        doc = area / "BENCHMARK.md"
        if not source.is_file() or not doc.is_file():
            raise ValueError(f"missing benchmark files: {key}")
        if not any(
            marker in source.read_text()
            for marker in ("criterion_group!", "BENCHMARK_SAMPLE", "BACKTEST_BENCHMARK_META")
        ):
            raise ValueError(f"benchmark has no measurement entry: {key}")
        scales_ok = len(row["sizes"]) >= 3 or (
            bool(row.get("external_input")) and len(row["sizes"]) == 1 and row.get("rounds", 0) >= 3
        )
        if not row["operation"] or not row["unit"] or not scales_ok:
            raise ValueError(f"incomplete benchmark contract: {key}")


def compare_reports(current: dict, baseline: dict) -> dict:
    if current.get("schema_version") != 1 or baseline.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema")
    for report in (current, baseline):
        environment = report.get("environment")
        storage = environment.get("storage") if isinstance(environment, dict) else None
        if (
            not isinstance(storage, dict)
            or type(storage.get("schema_version")) is not int
            or storage["schema_version"] != 1
            or not isinstance(storage.get("locations"), dict)
            or not storage["locations"]
        ):
            raise ValueError("incomparable storage evidence")
        required = {"temporary"}
        if report.get("case", "").startswith(("runtime/retained/", "backtest/retained/", "backend/backtest_chain/")):
            required.add("retained_input")
        if report.get("case", "").startswith("backend/backtest_chain/"):
            required.add("trace_input")
        if not required.issubset(storage["locations"]):
            raise ValueError("incomparable storage input locations")
        for description in storage["locations"].values():
            if (
                not isinstance(description, dict)
                or any(
                    not isinstance(description.get(key), str) or not description[key]
                    for key in ("mountpoint", "root", "filesystem", "source")
                )
                or any(
                    not isinstance(description.get(key), list)
                    or any(not isinstance(value, str) for value in description[key])
                    for key in ("mount_options", "filesystem_options")
                )
            ):
                raise ValueError("incomparable storage evidence")
    for key in ("schema_version", "case", "input_sha256", "result_sha256", "environment", "unit", "work_items"):
        if key not in current or current[key] != baseline.get(key):
            raise ValueError(f"incomparable {key}")
    for report in (current, baseline):
        if len(report["samples_ns"]) < 3 or any(
            type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in report["samples_ns"]
        ):
            raise ValueError("incomplete samples")
    return {"median_ratio": statistics.median(current["samples_ns"]) / statistics.median(baseline["samples_ns"])}


def compare_report_sets(current: list[dict], baseline: list[dict]) -> dict:
    by_case = []
    for reports in (current, baseline):
        rows = {row["case"]: row for row in reports}
        if not rows or len(rows) != len(reports):
            raise ValueError("empty or duplicate benchmark cases")
        by_case.append(rows)
    if by_case[0].keys() != by_case[1].keys():
        raise ValueError("incomplete benchmark case set")
    return {key: compare_reports(row, by_case[1][key]) for key, row in by_case[0].items()}


def compare_observation_overhead(off, detail):
    """只允许诊断模式不同；同输入/结果/二进制/冻结源码/环境的描述性中位数对照。"""
    previous = {row["case"]: row for row in off}
    if not previous or len(previous) != len(off):
        raise ValueError("empty or duplicate overhead cases")
    normalized_off = []
    normalized_detail = []
    for row in detail:
        baseline = previous.get(row["case"])
        if (
            baseline is None
            or not row["case"].startswith("runtime/retained/")
            or not row.get("build")
            or row["build"] != baseline.get("build")
        ):
            raise ValueError("overhead build or case mismatch")
        for sample, mode in [(baseline, "off"), (row, "detail")]:
            if sample["environment"].get("diagnostics_mode", "off") != mode:
                raise ValueError("overhead mode mismatch")
            close = sample.get("diagnostics_receipt", {})
            if close.get("shutdown_complete") is not True or any(
                type(close.get(key)) is not int or close[key] != 0 for key in ("dropped_events", "io_errors")
            ):
                raise ValueError("incomplete overhead diagnostics")
        normalized_off.append(
            dict(
                baseline,
                environment={key: value for key, value in baseline["environment"].items() if key != "diagnostics_mode"},
            )
        )
        normalized_detail.append(
            dict(
                row, environment={key: value for key, value in row["environment"].items() if key != "diagnostics_mode"}
            )
        )
    if {r["case"] for r in normalized_off} != previous.keys():
        raise ValueError("incomplete overhead cases")
    return dict(
        schema_version=1,
        comparison="diagnostic_overhead",
        same_binary=True,
        code_improvement_claim=False,
        cases=compare_report_sets(normalized_detail, normalized_off),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=Path("test-data/backtest-benchmarks/inventory.json"))
    parser.add_argument("--current", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.current or args.baseline:
        if not args.current or not args.baseline:
            parser.error("--current and --baseline must be supplied together")
        print(
            json.dumps(
                compare_report_sets(json.loads(args.current.read_text()), json.loads(args.baseline.read_text())),
                indent=2,
            )
        )
        return
    rows = json.loads(args.inventory.read_text())["cases"]
    validate_inventory(Path(__file__).resolve().parents[1], rows)
    print(json.dumps({"validated_cases": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
