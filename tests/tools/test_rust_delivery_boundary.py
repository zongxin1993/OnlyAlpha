import shutil
import tomllib
from pathlib import Path

import pytest

from scripts import rust_kernel_check as check
from scripts.rust_kernel_check import module_directory


def test_delivery_rejects_hidden_inputs_native_effects_and_calculation_edges(tmp_path: Path) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/market_data/delivery/src/state.rs"
    source.parent.mkdir(parents=True)
    for forbidden in (
        "use std::time::SystemTime;",
        "use std::{time::Instant};",
        "use std::thread;",
        "use std::io::stdin;",
        "use std::{io::stdout};",
        "use onlyalpha_runtime::OnlyRuntime;",
        "use onlyalpha_calculation::Value;",
        "use std::fs::File;",
        "use std::net::TcpStream;",
        "use std::process::Command;",
        'fn input() {std::env::var("X");}',
        "fn id() {uuid::Uuid::new_v4();}",
        'include!("../../clock/src/lib.rs");',
        '#[path="../../event/src/lib.rs"] mod event;',
        '#[cfg_attr(all(),path="elsewhere.rs")] mod hidden;',
        'const X:&str=env!("X");',
        'const X:&str=include_str!("../../../../../test-data/market-data-delivery/routing-v1.jsonl");',
        "use onlyalpha_indicator::Value;",
        "use onlyalpha_clock::OnlyClock;",
    ):
        source.write_text(forbidden)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_delivery_sources(tmp_path)
    source.write_text("//! Snapshot has no worker and no trading readiness.\npub struct Snapshot;\n")
    check.validate_delivery_sources(tmp_path)
    (source.parent.parent / "build.rs").write_text("fn main() {}")
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_delivery_sources(tmp_path)


def test_delivery_guard_permits_only_named_test_corpora(tmp_path: Path) -> None:
    test = tmp_path / "crates/onlyalpha-kernel/market_data/delivery/tests/conformance.rs"
    test.parent.mkdir(parents=True)
    for name in ("routing-v1.jsonl",):
        test.write_text(f'const V:&str=include_str!("../../../../../test-data/market-data-delivery/{name}");')
        check.validate_delivery_sources(tmp_path)
    for hidden in (
        'include_bytes!("../../../../../test-data/market-data-delivery/routing-v1.jsonl")',
        'include_str!("other.jsonl")',
        'include_str!(concat!("x","y"))',
    ):
        test.write_text(f"const X: &str = {hidden};")
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_delivery_sources(tmp_path)


def test_delivery_isolated_closure_and_source_guard() -> None:
    check.validate_delivery_sources(check.ROOT)


def test_delivery_isolated_closure(tmp_path: Path) -> None:
    manifest = check.isolated_delivery(check.ROOT, tmp_path / "isolated")
    root = manifest.parent
    assert set(tomllib.loads(manifest.read_text())["workspace"]["members"]) == {
        "crates/onlyalpha-kernel/domain",
        "crates/onlyalpha-kernel/market_data/delivery",
        "crates/onlyalpha-kernel/market_data/state",
        "crates/onlyalpha-kernel/market_data/construction",
    }
    local = {row["name"] for row in tomllib.loads((root / "Cargo.lock").read_text())["package"] if "source" not in row}
    assert local == {
        "onlyalpha-domain",
        "onlyalpha-market-data-state",
        "onlyalpha-market-data-construction",
        "onlyalpha-market-data-delivery",
    }
    assert (root / "test-data/market-data-delivery/routing-v1.jsonl").is_file()
    for path in (
        "crates/onlyalpha-kernel/core",
        "crates/onlyalpha-kernel/clock",
        "crates/onlyalpha-kernel/event",
        "src/onlyalpha",
        "plugs",
        "packages",
    ):
        assert not (root / path).exists()


def test_delivery_manifest_cannot_smuggle_edges_features_or_build_inputs(tmp_path: Path) -> None:
    for name in (
        "Cargo.toml",
        "Cargo.lock",
        "packages/onlyalpha-gateway-protocol/Cargo.toml",
        "packages/onlyalpha-calculation-worker/Cargo.toml",
        *[
            f"crates/onlyalpha-kernel/{module_directory(area)}/Cargo.toml"
            for area in (
                "domain",
                "core",
                "clock",
                "event",
                "market_data_state",
                "market_data_construction",
                "market_data_delivery",
                "calculation",
            )
        ],
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(check.ROOT / name, target)
    manifest = tmp_path / "crates/onlyalpha-kernel/market_data/delivery/Cargo.toml"
    original = manifest.read_text()
    for mutation in (
        original + 'onlyalpha-clock = {path="../clock"}\n',
        original.replace(
            'onlyalpha-domain = { path = "../../domain" }', 'alias = {package="onlyalpha-domain",path="../domain"}'
        ),
        original.replace('features = ["std"]', 'features = ["std","rand"]'),
        original + '[build-dependencies]\nonlyalpha-domain = {path="../domain"}\n',
        original + "[target.'cfg(unix)'.dependencies]\nonlyalpha-domain = {path=\"../domain\"}\n",
    ):
        manifest.write_text(mutation)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_workspace(tmp_path)
    manifest.write_text(original)
    lower = tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml"
    lower.write_text(lower.read_text() + 'onlyalpha-market-data-delivery = {path="../market_data_construction"}\n')
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_workspace(tmp_path)
