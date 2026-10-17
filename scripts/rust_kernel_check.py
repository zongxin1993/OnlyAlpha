"""Locked offline Linux validation of the non-activated Rust Kernel library."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dev_verification import source_inputs  # noqa: E402


def build_commands(target: str) -> list[list[str]]:
    base = ["--workspace", "--frozen", "--offline", "--target", target, "-j1"]
    return [
        ["cargo", "fmt", "--all", "--", "--check"],
        ["cargo", "clippy", *base, "--all-targets", "--", "-D", "warnings"],
        *[
            ["cargo", action, *base, *profile, *(["--", "--test-threads=1"] if action == "test" else [])]
            for action in ("test", "build")
            for profile in ([], ["--release"])
        ],
    ]


def compiler_environment(inherited: Mapping[str, str], target_dir: Path) -> dict[str, str]:
    env = {
        key: value for key, value in inherited.items() if not key.startswith(("RUST", "CARGO")) or key == "RUSTUP_HOME"
    }
    env.update(
        CARGO_HOME=str(target_dir.parent / "cargo-home"),
        CARGO_NET_OFFLINE="true",
        RUSTUP_AUTO_INSTALL="0",
        CARGO_BUILD_JOBS="1",
        CARGO_TARGET_DIR=str(target_dir),
    )
    return env


def main() -> int:
    artifacts = ROOT / "test-results/rust-kernel"
    artifacts.mkdir(parents=True, exist_ok=True)
    receipt = artifacts / "last-run.json"
    receipt.unlink(missing_ok=True)
    if sys.platform != "linux":
        raise ValueError("RUST_KERNEL_LINUX_REQUIRED: use the canonical dev container")
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    env = compiler_environment(os.environ, artifacts / "target")
    channel = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    env["RUSTUP_TOOLCHAIN"] = channel
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], cwd=ROOT, env=env, text=True)
    if f"release: {channel}\n" not in compiler or f"host: {target}\n" not in compiler:
        raise ValueError("RUST_KERNEL_TOOLCHAIN_MISMATCH")
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    if len(lock["package"]) != 1 or lock["package"][0]["name"] != "onlyalpha-kernel":
        raise ValueError("RUST_KERNEL_DEPENDENCY_REVIEW_REQUIRED")
    before = source_inputs(ROOT)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/predicate_vectors.py"), "--check"], cwd=ROOT, env=env, check=True
    )
    for command in build_commands(target):
        print("CHECK", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, env=env, check=True)
    if before != source_inputs(ROOT):
        raise ValueError("RUST_KERNEL_SOURCE_CHANGED")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    binaries = {
        profile: digest(artifacts / "target" / target / profile / "libonlyalpha_kernel.rlib")
        for profile in ("debug", "release")
    }
    binaries.update(
        {
            f"{profile}_predicate_diagnostic": digest(artifacts / "target" / target / profile / "predicate-diagnostic")
            for profile in ("debug", "release")
        }
    )
    receipt.write_text(
        json.dumps(
            {
                "compiler": compiler,
                "cargo": subprocess.check_output(["cargo", "--version"], cwd=ROOT, env=env, text=True).strip(),
                "target": target,
                "source_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                "cargo_lock_sha256": digest(ROOT / "Cargo.lock"),
                "vector_sha256": digest(ROOT / "test-data/predicate/boolean-v1.tsv"),
                "artifacts_sha256": binaries,
            },
            indent=2,
        )
        + "\n"
    )
    print("RUST_KERNEL_OFFLINE_DEBUG_RELEASE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
