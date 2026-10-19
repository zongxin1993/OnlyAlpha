from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_strategy_ledger_is_an_independent_semantic_closure(tmp_path: Path) -> None:
    check.validate_strategy_ledger_sources(check.ROOT)
    root = check.isolated_strategy_ledger(check.ROOT, tmp_path / "isolated").parent
    assert (root / "crates/onlyalpha-kernel/strategy_ledger/Cargo.toml").is_file()
    assert (root / "crates/onlyalpha-kernel/domain/Cargo.toml").is_file()
    assert not (root / "crates/onlyalpha-kernel/account").exists()
    assert not (root / "packages").exists()


@pytest.mark.parametrize(
    "code",
    (
        "use std::fs::File;",
        "use onlyalpha_account::Manager;",
        "use onlyalpha_position::Manager;",
        "use std::time::Instant;",
    ),
)
def test_strategy_ledger_rejects_effects_and_reverse_edges(tmp_path: Path, code: str) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/strategy_ledger/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text(code)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        check.validate_strategy_ledger_sources(tmp_path)


def test_actual_python_ledger_matches_independent_literals() -> None:
    from scripts.strategy_ledger_reference_check import reference_outputs

    assert len(reference_outputs()) == 4
