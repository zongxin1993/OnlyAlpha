"""Run the original financial value responsibility gate against its Rust owners."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "test-results/domain-mutation"
VERSION = "27.1.0"
# Decimal admission, precision and sign predicates moved into the numeric owner.
SCOPE = r"value[.]rs:|numeric[.]rs:.*\b(from_str|fractional_precision|result|is_negative|is_zero)\b"
REQUIRED = {
    "crates/domain/src/value.rs": {
        "validate_precision",
        "validate_quantity",
        "validate_multiplier",
        "validated_currency_code",
    },
    "crates/domain/src/numeric.rs": {
        "from_str",
        "fractional_precision",
        "result",
        "is_negative",
        "is_zero",
    },
}
SOURCE_FILES = (
    *REQUIRED,
    "crates/domain/src/lib.rs",
    "crates/domain/Cargo.toml",
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
)
MUTANT_FIELDS = {"name", "package", "file", "function", "span", "replacement", "genre"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("DOMAIN_MUTATION: " + message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def mutant_identity(row: dict) -> str:
    require(isinstance(row, dict) and set(row) == MUTANT_FIELDS, "invalid Mutant schema")
    require(all(isinstance(row[key], str) for key in ("name", "package", "file", "replacement")), "invalid identity")
    require(row["package"] == "onlyalpha-domain" and row["file"] in REQUIRED, "wrong mutant owner")
    require(row["name"].startswith(row["file"] + ":") and re.search(SCOPE, row["name"]), "wrong scope")
    require(
        row["genre"] in {"FnValue", "BinaryOperator", "UnaryOperator", "MatchArm", "MatchArmGuard", "StructField"},
        "unknown genre",
    )
    function = row["function"]
    require(
        isinstance(function, dict) and set(function) == {"function_name", "return_type", "span"}, "invalid function"
    )
    require(
        isinstance(function["function_name"], str) and isinstance(function["return_type"], str),
        "invalid function identity",
    )
    for span in (row["span"], function["span"]):
        require(isinstance(span, dict) and set(span) == {"start", "end"}, "invalid span")
        for point in span.values():
            require(isinstance(point, dict) and set(point) == {"line", "column"}, "invalid location")
            require(all(type(number) is int and number > 0 for number in point.values()), "invalid location number")
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def expected_mutants(rows) -> set[str]:
    require(isinstance(rows, list) and bool(rows), "empty or invalid mutant list")
    identities = set()
    owners = {file: set() for file in REQUIRED}
    for row in rows:
        require(isinstance(row, dict) and set(row) == MUTANT_FIELDS | {"diff"}, "invalid list schema")
        require(isinstance(row["diff"], str) and bool(row["diff"]), "missing mutant diff")
        identity = mutant_identity({key: value for key, value in row.items() if key != "diff"})
        require(identity not in identities, "duplicate listed mutant")
        identities.add(identity)
        owners[row["file"]].add(row["function"]["function_name"].rsplit("::", 1)[-1])
    require(all(required <= owners[file] for file, required in REQUIRED.items()), "missing financial value owner")
    return identities


def check_outcomes(result, expected: set[str]) -> dict[str, int]:
    fields = {
        "outcomes",
        "total_mutants",
        "missed",
        "caught",
        "timeout",
        "unviable",
        "success",
        "start_time",
        "end_time",
        "cargo_mutants_version",
    }
    require(isinstance(result, dict) and set(result) == fields, "invalid outcomes schema")
    require(result["cargo_mutants_version"] == VERSION, "wrong result tool version")
    require(all(isinstance(result[key], str) and result[key] for key in ("start_time", "end_time")), "unfinished run")
    counts = {key: result[key] for key in ("total_mutants", "caught", "missed", "timeout", "unviable", "success")}
    require(all(type(value) is int and value >= 0 for value in counts.values()), "invalid result counts")
    require(isinstance(result["outcomes"], list), "invalid outcome list")
    seen = set()
    baselines = 0
    actual = {"CaughtMutant": 0, "Unviable": 0}
    for row in result["outcomes"]:
        require(
            isinstance(row, dict) and set(row) == {"scenario", "summary", "log_path", "diff_path", "phase_results"},
            "invalid outcome",
        )
        require(isinstance(row["log_path"], str) and row["log_path"], "missing outcome log")
        phases = row["phase_results"]
        require(isinstance(phases, list) and bool(phases), "missing phase evidence")
        for phase in phases:
            require(
                isinstance(phase, dict) and set(phase) == {"phase", "duration", "process_status", "argv"},
                "invalid phase",
            )
            require(type(phase["duration"]) in (int, float) and phase["duration"] >= 0, "invalid duration")
            require(
                isinstance(phase["argv"], list)
                and phase["argv"]
                and all(isinstance(arg, str) for arg in phase["argv"]),
                "invalid argv",
            )
        scenario, summary = row["scenario"], row["summary"]
        if scenario == "Baseline":
            baselines += 1
            require(summary == "Success" and row["diff_path"] is None, "bad baseline")
            require([phase["phase"] for phase in phases] == ["Build", "Test"], "incomplete baseline")
            require(all(phase["process_status"] == "Success" for phase in phases), "failed baseline phase")
            continue
        require(isinstance(scenario, dict) and set(scenario) == {"Mutant"}, "unknown scenario")
        identity = mutant_identity(scenario["Mutant"])
        require(identity in expected and identity not in seen, "missing, duplicate or unrelated mutant")
        seen.add(identity)
        require(isinstance(row["diff_path"], str) and row["diff_path"], "missing mutant diff path")
        require(summary in actual, "surviving, timeout or unknown outcome")
        expected_phases = ["Build", "Test"] if summary == "CaughtMutant" else ["Build"]
        require([phase["phase"] for phase in phases] == expected_phases, "invalid phase sequence")
        require(all(phase["process_status"] == "Success" for phase in phases[:-1]), "failed preceding phase")
        status = phases[-1]["process_status"]
        require(
            isinstance(status, dict)
            and set(status) == {"Failure"}
            and type(status["Failure"]) is int
            and status["Failure"] != 0,
            "outcome lacks failed process",
        )
        actual[summary] += 1
    require(baselines == 1 and seen == expected, "incomplete or duplicate run")
    require(
        counts
        == {
            "total_mutants": len(expected),
            "caught": actual["CaughtMutant"],
            "unviable": actual["Unviable"],
            "missed": 0,
            "timeout": 0,
            "success": 0,
        }
        and counts["caught"] > 0,
        "inconsistent counts or no caught mutant",
    )
    return counts


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Keep each run, including failed runs; a prior outcomes.json can never be reused.
    run = Path(tempfile.mkdtemp(prefix="run-", dir=OUTPUT))
    hashes = source_hashes()
    environment = compiler_environment(os.environ, run / "target")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    version = subprocess.run(
        ["cargo", "mutants", "--version"], cwd=ROOT, env=environment, check=True, capture_output=True, text=True
    ).stdout.strip()
    require(version == f"cargo-mutants {VERSION}", "wrong installed tool version")
    (run / "inputs.json").write_text(json.dumps({"source_sha256": hashes, "tool": version}, indent=2) + "\n")
    command = [
        "cargo",
        "mutants",
        "--no-config",
        "--package",
        "onlyalpha-domain",
        "--file",
        "crates/domain/src/value.rs",
        "--file",
        "crates/domain/src/numeric.rs",
        "--re",
        SCOPE,
        "--test-package",
        "onlyalpha-domain",
        "--baseline",
        "run",
        "--jobs",
        "1",
        "--jobserver-tasks",
        "1",
        "--cargo-arg=--locked",
        "--output",
        str(run),
    ]
    with (run / "mutants-list.json").open("w") as target:
        subprocess.run(command + ["--list", "--json"], cwd=ROOT, env=environment, check=True, stdout=target)
    expected = expected_mutants(read_json(run / "mutants-list.json"))
    require(source_hashes() == hashes, "source changed during listing")
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    counts = check_outcomes(read_json(run / "mutants.out/outcomes.json"), expected)
    require(source_hashes() == hashes, "source changed during campaign")
    (run / "verified.json").write_text(
        json.dumps({"source_sha256": hashes, "tool": version, "counts": counts}, indent=2) + "\n"
    )
    print(json.dumps({"output": str(run), **counts}, sort_keys=True))


if __name__ == "__main__":
    main()
