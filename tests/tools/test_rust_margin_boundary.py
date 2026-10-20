"""Margin is isolated canonical state, with no market policy or I/O authority."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_margin_module_has_only_domain_local_dependency() -> None:
    area = ROOT / "crates/onlyalpha-kernel/margin"
    assert area.is_dir(), "Rust Margin module is missing"
    manifest = tomllib.loads((area / "Cargo.toml").read_text())
    assert {name for name, value in manifest["dependencies"].items() if "path" in value} == {"onlyalpha-domain"}


def test_margin_sources_reject_effects_and_reverse_edges(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_margin_sources

    area = tmp_path / "crates/onlyalpha-kernel/margin/src"
    area.mkdir(parents=True)
    path = area / "lib.rs"
    for source in (
        "use onlyalpha_runtime::Runtime;",
        "use std::fs::File;",
        "use onlyalpha_account::Manager;",
        "use std::time::SystemTime;",
        'const X: &str = include_str!("/tmp/hidden");',
    ):
        path.write_text(source)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_margin_sources(tmp_path)
    path.write_text("use onlyalpha_domain::value::OnlyCurrency;")
    validate_margin_sources(tmp_path)


def test_margin_isolated_closure_contains_only_its_declared_domain(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import isolated_margin

    manifest = isolated_margin(ROOT, tmp_path / "source")
    workspace = tomllib.loads(manifest.read_text())["workspace"]
    assert set(workspace["members"]) == {"crates/onlyalpha-kernel/domain", "crates/onlyalpha-kernel/margin"}
    assert not (manifest.parent / "crates/onlyalpha-kernel/execution").exists()


def test_margin_common_reference_matches_independent_money_expectations() -> None:
    from scripts.margin_reference_check import EXPECTED, cases, check_fixture, python_reference

    check_fixture()
    for case in cases():
        assert python_reference(case) == EXPECTED
