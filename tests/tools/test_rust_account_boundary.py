from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_account_declares_and_extracts_only_its_semantic_closure(tmp_path: Path) -> None:
    check.validate_account_sources(check.ROOT)
    root = check.isolated_account(check.ROOT, tmp_path / "isolated").parent
    assert (root / "crates/onlyalpha-kernel/account/Cargo.toml").is_file()
    assert (root / "crates/onlyalpha-kernel/domain/Cargo.toml").is_file()
    assert not (root / "crates/onlyalpha-kernel/strategy").exists()
    assert not (root / "packages").exists()


@pytest.mark.parametrize(
    "code",
    ("use std::fs::File;", "use onlyalpha_risk::Risk;", "use onlyalpha_strategy::Program;", "use std::time::Instant;"),
)
def test_account_rejects_effects_and_reverse_layers(tmp_path: Path, code: str) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/account/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text(code)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        check.validate_account_sources(tmp_path)


def test_actual_python_account_reference_matches_independent_vectors() -> None:
    from scripts.account_reference_check import reference_outputs

    assert len(reference_outputs()) >= 3
