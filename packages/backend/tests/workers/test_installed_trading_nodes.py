"""Real installed source compiler plus native Strategy NodePort; technical evidence only."""

from __future__ import annotations

import json
import os
import platform
import re
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
    request = output / "inputs.json"
    request.write_text(
        json.dumps(
            {
                "factor_revision": factor["revision"],
                "factor_parameters": {
                    key: value["value"]["value"]
                    for instance in instances
                    if instance["type_reference"]["kind"] == "FACTOR"
                    for key, value in instance["parameters"].items()
                },
                "base": base,
                "strategy": json.loads(
                    (root / "examples/private-assets/strategy/simple_momentum/strategy.json").read_text()
                )["strategy"]["definition"],
                "instances": instances,
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
    assert re.search(r"^test result: ok\. [1-9]\d* passed;", result.stdout, re.MULTILINE), result.stdout
    return result.stdout + result.stderr


@pytest.mark.timeout(180)
def test_actual_installed_trading_nodes_and_fresh_restore(tmp_path: Path) -> None:
    installed_trading_case(tmp_path, "installed_trading_algorithms::")


@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    "selector",
    [
        "installed_trading_algorithms::compiler_child_owner_joins_on_cancel_and_refuses_foreign_source_bytes",
        "installed_trading_algorithms::native_factor_batch_preserves_exact_volume_momentum_vectors",
        "installed_trading_algorithms::next_open_trading::cancelled_or_incomplete_memory_run_cannot_produce_a_completed_backtest",
    ],
)
def test_actual_compiler_owner_and_native_vectors(tmp_path: Path, selector: str) -> None:
    installed_trading_case(tmp_path, selector)


@pytest.mark.timeout(180)
def test_installed_latest_closed_full_interval_in_production_profile(tmp_path: Path) -> None:
    installed_trading_case(
        tmp_path,
        "installed_trading_algorithms::next_open_trading::compiled_factor_to_native_next_open_memory_backtest_and_verification",
        release=True,
    )
