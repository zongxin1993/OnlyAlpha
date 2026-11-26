"""在已冻结的开发验证环境中串行编译、预检和采集库基准。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from scripts.node_database import prepare as prepare_node_database
from scripts.rust_benchmark import (
    benchmark_input_identity,
    chain_reports,
    criterion_reports,
    criterion_samples,
    diagnostic_receipt,
    result_identity,
    retained_reports,
    storage_conditions,
    validate_fixture_provenance,
    validate_inventory,
)
from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_benchmarks(rows, crates, targets, diagnostics):
    if diagnostics not in {"off", "detail"}:
        raise ValueError("unsupported benchmark diagnostics mode")
    if set(crates) - {r["crate"] for r in rows} or set(targets) - {r["target"] for r in rows}:
        raise ValueError("unknown benchmark selection")
    selected = [r for r in rows if (not crates or r["crate"] in crates) and (not targets or r["target"] in targets)]
    if not selected:
        raise ValueError("empty benchmark selection")
    if diagnostics != "off" and any((r["crate"], r["target"]) != ("runtime", "retained") for r in selected):
        raise ValueError("detail benchmark requires runtime retained target")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "smoke", "reference"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crate", action="append", default=[])
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--diagnostics", choices=("off", "detail"), default="off")
    parser.add_argument(
        "--scope",
        choices=("memory.execution", "pg.recovery", "result.read"),
        default="memory.execution",
        help="后端三口径选择：memory.execution（内存执行）、pg.recovery（PG 正式事实恢复，需 ONLYALPHA_POSTGRES_DSN）、result.read（结果读取）",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "test-data/backtest-benchmarks/inventory.json").read_text())["cases"]
    validate_inventory(root, rows)
    validate_fixture_provenance(root / "test-data/backtest-benchmarks")
    rows = select_benchmarks(rows, args.crate, args.target, args.diagnostics)
    args.output.mkdir(parents=True, exist_ok=False)
    env = compiler_environment(os.environ, Path("/tmp/oa-target"))
    env["OA_BENCH_DIAGNOSTICS"] = args.diagnostics
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    compiler = subprocess.check_output(["rustc", "-Vv"], env=env, text=True)
    cpu_text = Path("/proc/cpuinfo").read_text()
    hardware = dict(
        logical_cpus=os.cpu_count(),
        cpu_identity=sorted(
            set(
                line.strip()
                for line in cpu_text.splitlines()
                if line.startswith(
                    (
                        "model name",
                        "CPU implementer",
                        "CPU architecture",
                        "CPU variant",
                        "CPU part",
                        "CPU revision",
                        "Features",
                    )
                )
            )
        ),
        memory_limit=Path("/sys/fs/cgroup/memory.max").read_text().strip(),
        cpu_limit=Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
    )
    identity = dict(
        schema_version=1,
        diagnostics_mode=args.diagnostics,
        compiler=compiler,
        platform={key: value for key, value in platform.uname()._asdict().items() if key != "node"},
        hardware=hardware,
        lock_sha256=sha(root / "Cargo.lock"),
        profile="bench",
        features="default",
        cache="warm; no OS cache eviction",
        cpu=Path("/proc/cpuinfo").read_text(),
        mounts=Path("/proc/self/mountinfo").read_text(),
        source=json.loads((root / ".onlyalpha-dev-source-cut.json").read_text()),
        input_sha256=sha(root / "test-data/backtest-benchmarks/provenance.json"),
    )
    (args.output / "environment.json").write_text(json.dumps(identity, indent=2))
    for row in rows:
        package = "onlyalpha-" + row["crate"]
        directory = args.output / row["crate"] / row["target"]
        directory.mkdir(parents=True)
        command = [
            "cargo",
            "bench",
            "--frozen",
            "--offline",
            "-p",
            package,
            "--bench",
            row["target"],
            "--no-run",
            "--message-format=json",
        ]
        build = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True)
        (directory / "build.jsonl").write_text(build.stdout)
        (directory / "build.stderr").write_text(build.stderr)
        build.check_returncode()
        artifacts = [
            v
            for line in build.stdout.splitlines()
            if (v := json.loads(line)).get("reason") == "compiler-artifact"
            and v.get("executable")
            and v["target"]["name"] == row["target"]
        ]
        if len(artifacts) != 1:
            raise ValueError("ambiguous benchmark binary")
        executable = Path(artifacts[0]["executable"])
        metadata = dict(identity, case=row, binary_sha256=sha(executable), preflight="not run", measurement="not run")
        locations = {"temporary": str(Path(tempfile.gettempdir()).resolve())}
        metadata["storage"] = storage_conditions(identity["mounts"], locations)
        metadata["input_sha256"] = benchmark_input_identity(identity["source"]["inputs"], row)
        metadata["input_identity_schema"] = "captured-harness-helpers-fixtures-v1"
        (directory / "identity.json").write_text(json.dumps(metadata, indent=2))
        if args.mode == "check":
            print("COMPILED", package, row["target"], flush=True)
            continue
        if row.get("rounds"):
            env["OA_BENCH_ROUNDS"] = str(row["rounds"])
            if row["crate"] == "backend":
                if args.scope == "pg.recovery" and not os.environ.get("ONLYALPHA_POSTGRES_DSN"):
                    raise ValueError("pg.recovery benchmark requires ONLYALPHA_POSTGRES_DSN")
                env["OA_BENCH_SCOPE"] = args.scope
                metadata["scope"] = args.scope
                if args.scope == "pg.recovery":
                    env["ONLYALPHA_POSTGRES_DSN"] = prepare_node_database(
                        os.environ["ONLYALPHA_POSTGRES_DSN"], test=True
                    )
            metadata["storage"] = storage_conditions(identity["mounts"], locations)
            env["OA_BENCH_STORAGE"] = json.dumps(metadata["storage"], sort_keys=True)
            with (directory / "reference.log").open("w") as stream:
                subprocess.run(
                    [str(executable)], cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True
                )
            log = (directory / "reference.log").read_text()
            if (row["crate"], row["target"]) == ("runtime", "retained"):
                metadata["diagnostics_receipt"] = diagnostic_receipt(log, args.diagnostics)
            parser = chain_reports if row["crate"] == "backend" else retained_reports
            reports = parser(log, metadata)
            metadata.update(preflight="passed per-round assertions", measurement="complete")
            (directory / "identity.json").write_text(json.dumps(metadata, indent=2))
            (directory / "report.json").write_text(json.dumps(reports, indent=2))
            print("VERIFIED", package, row["target"], "complete fixed samples", flush=True)
            continue
        with (directory / "smoke.log").open("w") as stream:
            subprocess.run(
                [str(executable), "--test"], cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True
            )
        metadata["preflight"] = "passed all source assertions"
        metadata["result_sha256"] = result_identity((directory / "smoke.log").read_text())
        if args.mode == "reference":
            criterion = Path(env["CARGO_TARGET_DIR"]) / "criterion"
            # Criterion identifiers are local to each executable. Preserve each result
            # before the next crate uses the same group name.
            if criterion.exists():
                shutil.rmtree(criterion)
            with (directory / "reference.log").open("w") as stream:
                subprocess.run(
                    [str(executable), "--bench"], cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True
                )
            if result_identity((directory / "reference.log").read_text()) != metadata["result_sha256"]:
                raise ValueError("measurement result differs from preflight")
            shutil.copytree(criterion, directory / "criterion")
            samples = []
            for path in sorted((directory / "criterion").rglob("new/sample.json")):
                case = path.parent / "benchmark.json"
                estimates = json.loads((path.parent / "estimates.json").read_text())
                samples.append(
                    dict(
                        case=json.loads(case.read_text()),
                        samples_ns=criterion_samples(json.loads(path.read_text())),
                        criterion_estimates=estimates,
                    )
                )
            if not samples:
                raise ValueError("missing Criterion measurement")
            metadata["measurement"] = "complete"
            (directory / "samples.json").write_text(json.dumps(samples, indent=2))
            (directory / "report.json").write_text(json.dumps(criterion_reports(samples, metadata), indent=2))
        (directory / "identity.json").write_text(json.dumps(metadata, indent=2))
        print("VERIFIED", package, row["target"], metadata["measurement"], flush=True)


if __name__ == "__main__":
    main()
