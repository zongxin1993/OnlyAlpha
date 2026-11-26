"""Regression tests for the L3 WASM host workspace and source boundary guards."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.rust_kernel_check import (
    ROOT,
    affected_packages,
    isolated_wasm_host,
    validate_wasm_host_sources,
    validate_workspace,
)


def _copy_minimal_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    shutil.copyfile(ROOT / "Cargo.toml", workspace / "Cargo.toml")
    shutil.copyfile(ROOT / "Cargo.lock", workspace / "Cargo.lock")
    for rel in (
        "crates",
        "plugs",
        "packages/backend",
    ):
        src = ROOT / rel
        dst = workspace / rel
        for manifest in src.rglob("Cargo.toml"):
            target = dst / manifest.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest, target)
    return workspace


def test_wasm_host_sources_and_wit_contract_pass_guard() -> None:
    validate_wasm_host_sources(ROOT)
    assert affected_packages(ROOT, ("contracts/wasm/v1/onlyalpha-plugin.wit",)) == ("onlyalpha-wasm-host",)


def test_wasm_host_source_guard_rejects_unsafe_and_wasi_import(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    src_root = ROOT / "crates/wasm-host"
    for src_file in src_root.rglob("*"):
        if src_file.is_file():
            dst_file = workspace / "crates/wasm-host" / src_file.relative_to(src_root)
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_file, dst_file)
    wit = workspace / "contracts/wasm/v1/onlyalpha-plugin.wit"
    wit.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "contracts/wasm/v1/onlyalpha-plugin.wit", wit)
    validate_wasm_host_sources(workspace)

    # Injecting `unsafe` must fail closed.
    lib_rs = workspace / "crates/wasm-host/src/lib.rs"
    original = lib_rs.read_text(encoding="utf-8")
    lib_rs.write_text(original + "\nfn bad() { unsafe {} }\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_wasm_host_sources(workspace)

    # Injecting `wasmtime_wasi` must fail closed.
    lib_rs.write_text(original + "\nuse wasmtime_wasi::WasiCtx;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_wasm_host_sources(workspace)

    # Removing the versioned WIT contract must fail closed.
    lib_rs.write_text(original, encoding="utf-8")
    wit.unlink()
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_wasm_host_sources(workspace)


def test_workspace_guard_rejects_wasmtime_wasi_dependency(tmp_path: Path) -> None:
    workspace = _copy_minimal_workspace(tmp_path)
    validate_workspace(workspace)

    wasm_manifest = workspace / "crates/wasm-host/Cargo.toml"
    wasm_manifest.write_text(
        wasm_manifest.read_text(encoding="utf-8") + 'wasmtime-wasi = "=51.0.0"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_workspace(workspace)


def test_isolated_wasm_host_materializes_wit_contract(tmp_path: Path) -> None:
    manifest = isolated_wasm_host(ROOT, tmp_path / "isolated")
    assert manifest.is_file()
    assert (manifest.parent / "contracts/wasm/v1/onlyalpha-plugin.wit").is_file()
    assert (manifest.parent / "crates/wasm-host/Cargo.toml").is_file()
    assert (manifest.parent / "crates/operators/Cargo.toml").is_file()
