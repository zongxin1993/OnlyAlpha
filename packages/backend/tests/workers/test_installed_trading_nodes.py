"""Real SDK process plus native Strategy NodePort; technical evidence only."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest


def installed_trading_environment(root: Path, output: Path) -> dict[str, str]:
    from scripts.build_algorithm_sdk import ROOT, install

    if root.resolve() != ROOT.resolve():
        raise ValueError("TRADING_TEST_SOURCE_ROOT_MISMATCH")
    installation = output / "installed"
    artifact = install(output / "wheels", installation)
    factor = json.loads((root / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    fields = (
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    )
    sources = [{key: factor["revision"][key] for key in fields}]
    # Observe exact installed descriptors, without executing authored math or
    # creating an application/Runtime/Research capability.
    observation = subprocess.run(
        [
            str(installation / "bin/python"),
            "-B",
            "-I",
            "-c",
            "import json,sys;from onlyalpha_backend_algorithms.research_resolution import registry_for_sources,private_calculation_records;"
            "r,_=registry_for_sources(json.load(sys.stdin));print(json.dumps(private_calculation_records(r.backend_registrations())))",
        ],
        input=json.dumps(sources),
        capture_output=True,
        text=True,
        env={},
        check=False,
        timeout=15,
    )
    assert observation.returncode == 0, observation.stderr
    base = next(
        json.loads(line)["record"]
        for line in (root / "test-data/domain/fact-records-v1.jsonl").read_text().splitlines()
        if json.loads(line)["id"] == "bar"
    )
    base["bar_type"]["instrument_id"]["symbol"]["value"] = "BTCUSDT"
    base["bar_type"]["instrument_id"]["venue"]["value"] = "BINANCE"
    # These are reusable authoring inputs, not upgraded immutable Definitions.
    # The current graph/identities are rebuilt in the actually tested Rust ELF.
    historical = json.loads(
        (root / "packages/backend/tests/application/fixtures/strategy_calculations.json").read_text()
    )
    instances = historical["instances"]
    for instance in instances:
        reference = instance["type_reference"]
        if reference["type_id"].startswith("onlyalpha.operator."):
            reference["semantic_version"] = "2"
    core = next((output / "wheels").glob("onlyalpha-*.whl"))
    core_artifact = {
        "path": str(core),
        "sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "size": core.stat().st_size,
        "distribution_version": core.name.split("-")[1],
    }
    resolution = {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1",
        "sources": sources,
        "instances": instances,
        "core_artifact": core_artifact,
        "operator_artifact": None,
        "target_artifact": None,
    }
    request = output / "inputs.json"
    request.write_text(
        json.dumps(
            {
                "sources": sources,
                "registrations": json.loads(observation.stdout),
                "base": base,
                "strategy": json.loads(
                    (root / "examples/private-assets/strategy/simple_momentum/strategy.json").read_text()
                )["strategy"]["definition"],
                "calculations": {
                    "instances": instances,
                    "factor_revision_dependencies": historical["factor_revision_dependencies"],
                },
                "resolution_request": resolution,
            }
        )
    )
    return {
        "ONLYALPHA_TRADING_TEST_INPUT": str(request),
        "ONLYALPHA_TRADING_TEST_INSTALLATION": str(installation),
        "ONLYALPHA_TRADING_TEST_ARTIFACT": artifact,
    }


def build_installed_trading_binary(
    *, release: bool = True, build_timeout: int | None = 120
) -> tuple[Path, dict[str, str]]:
    from scripts.build_algorithm_sdk import ROOT
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    environment = compiler_environment(os.environ, ROOT / "test-results/rust-kernel/target")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    built = subprocess.run(
        [
            "cargo",
            "test",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
            *(["--release"] if release else []),
            "-p",
            "onlyalpha-backend",
            "--test",
            "workers_trading",
            "--no-run",
            "--message-format=json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=build_timeout,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    executables = [
        record["executable"]
        for line in built.stdout.splitlines()
        if line.startswith("{")
        for record in [json.loads(line)]
        if record.get("reason") == "compiler-artifact"
        and record["target"]["name"] == "workers_trading"
        and record.get("executable")
    ]
    assert len(executables) == 1
    return Path(executables[0]), environment


def installed_trading_case(
    tmp_path: Path, selector: str, *, release: bool = True, build_timeout: int | None = 120
) -> str:
    from scripts.build_algorithm_sdk import ROOT

    installed = installed_trading_environment(ROOT, tmp_path)
    binary, environment = build_installed_trading_binary(release=release, build_timeout=build_timeout)
    environment.update(installed)
    # Exercise the actual selected ELF under the same 128 MiB Shipping guard.
    # Debug-only sections are removed from this isolated test copy.
    executable = tmp_path / "installed-trading-tests"
    shutil.copyfile(binary, executable)
    subprocess.run(["strip", "--strip-all", str(executable)], check=True, timeout=30)
    executable.chmod(0o500)
    assert executable.stat().st_size <= 128 * 1024 * 1024
    result = subprocess.run(
        [str(executable), selector, "--nocapture", "--test-threads=1"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=150,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.mark.timeout(180)
def test_actual_installed_trading_nodes_and_fresh_restore(tmp_path: Path) -> None:
    installed_trading_case(tmp_path, "installed_trading_algorithms::")


@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    "selector",
    [
        "installed_trading_algorithms::constructor_",
        "installed_trading_algorithms::trading_capabilities_metadata_",
        "installed_trading_algorithms::next_open_trading::native_terminal_readonly_snapshot_verifies_cancelled_original_journal_and_rejects_splices",
    ],
)
def test_actual_installed_constructor_and_metadata_owners(tmp_path: Path, selector: str) -> None:
    installed_trading_case(tmp_path, selector)


@pytest.mark.timeout(180)
def test_actual_native_readonly_source_in_production_profile(tmp_path: Path) -> None:
    # The same 150s execution budget and exact assertions. The development
    # profile timed out; measure the actual shipping optimization before tuning.
    installed_trading_case(
        tmp_path,
        "installed_trading_algorithms::next_open_trading::native_terminal_readonly_snapshot_verifies_cancelled_original_journal_and_rejects_splices",
        release=True,
    )


@pytest.mark.timeout(180)
def test_installed_latest_closed_full_interval_and_recovery_in_production_profile(tmp_path: Path) -> None:
    installed_trading_case(
        tmp_path,
        "installed_trading_algorithms::next_open_trading::installed_source_to_native_next_open_kernel_and_durable_recovery",
        release=True,
    )
