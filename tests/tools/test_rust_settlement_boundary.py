"""Settlement stays a Domain-only semantic authority."""

from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_settlement_is_an_independent_domain_only_closure(tmp_path: Path) -> None:
    check.validate_settlement_sources(check.ROOT)
    root = check.isolated_settlement(check.ROOT, tmp_path / "isolated").parent
    assert (root / "crates/onlyalpha-kernel/settlement/Cargo.toml").is_file()
    assert not (root / "crates/onlyalpha-kernel/execution").exists()


@pytest.mark.parametrize(
    "code",
    (
        "use std::fs::File;",
        "use std::net::TcpStream;",
        "use std::time::SystemTime;",
        "use onlyalpha_execution::Components;",
        "use onlyalpha_runtime::Runtime;",
    ),
)
def test_settlement_rejects_io_and_reverse_authority_edges(tmp_path: Path, code: str) -> None:
    path = tmp_path / "crates/onlyalpha-kernel/settlement/src/lib.rs"
    path.parent.mkdir(parents=True)
    path.write_text(code)
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_settlement_sources(tmp_path)


def test_shared_settlement_cases_consume_actual_python_authorities() -> None:
    from scripts.settlement_reference_check import cases, python_reference

    for case in cases():
        assert python_reference(case["fixture"])[0] == case["expected"]
