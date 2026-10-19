"""Execution has a real isolated source boundary, not an application escape."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_execution_module_is_present_with_exact_lower_layer_edges() -> None:
    area = ROOT / "crates/onlyalpha-kernel/execution"
    assert area.is_dir(), "Rust Execution module is missing"
    manifest = tomllib.loads((area / "Cargo.toml").read_text())
    local = {name for name, config in manifest["dependencies"].items() if "path" in config}
    assert local == {
        "onlyalpha-domain",
        "onlyalpha-order",
        "onlyalpha-position",
        "onlyalpha-account",
        "onlyalpha-strategy-ledger",
        "onlyalpha-risk",
        "onlyalpha-fee",
        "onlyalpha-settlement",
    }


def test_execution_sources_reject_side_effects_and_reverse_edges(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_execution_sources

    area = tmp_path / "crates/onlyalpha-kernel/execution/src"
    area.mkdir(parents=True)
    source = area / "lib.rs"
    for text in (
        "use onlyalpha_runtime::Runtime;",
        "use std::fs::File;",
        'const X:&str=include_str!("/tmp/escape");',
        "use std::time::SystemTime;",
    ):
        source.write_text(text)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_execution_sources(tmp_path)
    source.write_text("use onlyalpha_order::Manager;")
    validate_execution_sources(tmp_path)


def test_execution_domain_inputs_are_bound_to_the_actual_generator() -> None:
    from scripts.execution_reference_check import check_fixture

    check_fixture()
