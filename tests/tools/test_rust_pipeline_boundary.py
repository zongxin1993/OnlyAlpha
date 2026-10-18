from pathlib import Path

from scripts import rust_kernel_check as check


def test_pipeline_has_only_its_declared_semantic_closure(tmp_path: Path) -> None:
    check.validate_pipeline_sources(check.ROOT)
    root = check.isolated_pipeline(check.ROOT, tmp_path / "pipeline").parent
    assert (root / "crates/onlyalpha-kernel/market_data/pipeline/Cargo.toml").is_file()
    assert (root / "crates/onlyalpha-kernel/calculation/Cargo.toml").is_file()
    assert not (root / "packages").exists()
    assert not (root / "crates/onlyalpha-kernel/core").exists()


def test_pipeline_rejects_effects_and_reverse_dependencies(tmp_path: Path) -> None:
    import pytest

    source = tmp_path / "crates/onlyalpha-kernel/market_data/pipeline/src/lib.rs"
    source.parent.mkdir(parents=True)
    for content in (
        "use onlyalpha_calculation_worker::Worker;",
        "use onlyalpha_kernel::Runtime;",
        "use std::time::Instant;",
        'include!("../../core/src/lib.rs");',
    ):
        source.write_text(content)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_pipeline_sources(tmp_path)


def test_pipeline_contract_has_exact_declared_dependencies() -> None:
    import tomllib

    check.validate_workspace(check.ROOT)
    manifest = check.ROOT / "crates/onlyalpha-kernel/market_data/pipeline/Cargo.toml"
    assert tomllib.loads(manifest.read_text())["dependencies"] == check.PIPELINE_DEPENDENCIES
