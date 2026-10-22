"""Reuse the canonical, guarded, serial PostgreSQL test namespace."""

from __future__ import annotations

import os
import platform
import subprocess
import tomllib
from pathlib import Path

import pytest

from tests.research.postgres.conftest import postgres_dsn

__all__ = ["postgres_dsn"]


@pytest.fixture(scope="session")
def native_probe() -> Path:
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    root = Path(__file__).resolve().parents[3]
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    output = root / "test-results/rust-kernel/target"
    environment = compiler_environment(os.environ, output)
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    subprocess.run(
        [
            "cargo",
            "build",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-product-runtime",
            "--example",
            "command-postgres-probe",
        ],
        cwd=root,
        env=environment,
        check=True,
    )
    return output / target / "debug/examples/command-postgres-probe"
