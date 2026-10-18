from pathlib import Path

from scripts import rust_kernel_check as check


def test_strategy_has_only_its_declared_semantic_closure(tmp_path: Path) -> None:
    check.validate_strategy_sources(check.ROOT)
    root = check.isolated_strategy(check.ROOT, tmp_path / "strategy").parent
    assert (root / "crates/onlyalpha-kernel/strategy/Cargo.toml").is_file()
    assert not (root / "packages").exists()
    assert (root / "crates/onlyalpha-kernel/market_data/construction").exists()
    assert not (root / "crates/onlyalpha-kernel/market_data/pipeline").exists()


def test_strategy_source_guard_rejects_reverse_layers_and_effects(tmp_path: Path) -> None:
    import pytest

    source = tmp_path / "crates/onlyalpha-kernel/strategy/src/lib.rs"
    source.parent.mkdir(parents=True)
    for code in (
        "use onlyalpha_market_data_pipeline::MarketDataPipeline;",
        "use onlyalpha_runtime::Runtime;",
        "use std::fs::File;",
        "use std::time::Instant;",
    ):
        source.write_text(code)
        with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
            check.validate_strategy_sources(tmp_path)
