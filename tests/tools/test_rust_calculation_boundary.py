import tomllib
from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_calculation_source_guard_rejects_effects_and_reverse_imports(tmp_path: Path) -> None:
    path = tmp_path / "crates/onlyalpha-kernel/calculation/src/lib.rs"
    path.parent.mkdir(parents=True)
    for code in (
        "use std::time::SystemTime;",
        "use onlyalpha_runtime::Runtime;",
        "use onlyalpha_kernel::Predicate;",
        "use onlyalpha_predicates::Predicate;",
        "use onlyalpha_indicator::Sma;",
        'include!("elsewhere.rs");',
        "use std::fs::File;",
    ):
        path.write_text(code)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_calculation_sources(tmp_path)
    path.write_text("pub struct Definition;\n")
    check.validate_calculation_sources(tmp_path)


def test_calculation_can_build_without_other_kernel_modules(tmp_path: Path) -> None:
    manifest = check.isolated_calculation(check.ROOT, tmp_path / "source")
    root = manifest.parent
    assert (root / "crates/onlyalpha-kernel/calculation/Cargo.toml").exists()
    assert not (root / "crates/onlyalpha-kernel/domain").exists()
    assert not (root / "crates/onlyalpha-kernel/predicates").exists()
    assert (root / "test-data/calculation/definitions-v1.jsonl").exists()


def test_isolated_lock_excludes_unreachable_registry_packages(tmp_path: Path) -> None:
    manifest = check.isolated_calculation(check.ROOT, tmp_path / "source")
    packages = tomllib.loads((manifest.parent / "Cargo.lock").read_text())["package"]
    names = {package["name"] for package in packages}
    assert {"onlyalpha-calculation", "bigdecimal", "sha2", "serde_json"} <= names
    assert not {"onlyalpha-domain", "tz-rs", "jiff", "jiff-core"} & names
