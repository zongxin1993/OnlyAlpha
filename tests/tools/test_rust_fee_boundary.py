"""Fee semantic isolation and authority dependency direction."""

from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_fee_is_an_independent_domain_only_closure(tmp_path: Path) -> None:
    check.validate_fee_sources(check.ROOT)
    isolated = check.isolated_fee(check.ROOT, tmp_path / "isolated").parent
    assert (isolated / "crates/onlyalpha-kernel/fee/Cargo.toml").is_file()
    assert not (isolated / "crates/onlyalpha-kernel/execution").exists()
    assert not (isolated / "packages").exists()


@pytest.mark.parametrize(
    "code",
    (
        "use std::fs::File;",
        "use std::net::TcpStream;",
        "use std::time::SystemTime;",
        "use onlyalpha_execution::Components;",
        "use onlyalpha_runtime::Runtime;",
        'const X: &str = include_str!("/tmp/hidden");',
    ),
)
def test_fee_rejects_io_and_reverse_authority_edges(tmp_path: Path, code: str) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/fee/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text(code)
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_fee_sources(tmp_path)


def test_shared_fee_values_consume_actual_python_authorities() -> None:
    from scripts.fee_reference_check import cases

    values = cases()
    assert values[0][1] == ["5.00", "0.00", "2.00"]
    assert values[1][1] == ["5.00", "5.00", "5.00"]


def test_isolated_members_support_valid_multiline_workspace(tmp_path: Path) -> None:
    import shutil
    import tomllib

    source = tmp_path / "source"
    source.mkdir()
    for name in ("Cargo.lock", "rust-toolchain.toml"):
        shutil.copyfile(check.ROOT / name, source / name)
    for name in ("crates/onlyalpha-kernel/domain", "crates/onlyalpha-kernel/fee", "test-data/domain", "test-data/fee"):
        shutil.copytree(check.ROOT / name, source / name)
    original = (check.ROOT / "Cargo.toml").read_text()
    (source / "Cargo.toml").write_text(
        '[workspace]\nmembers = [\n"crates/onlyalpha-kernel/domain",\n"crates/onlyalpha-kernel/fee",\n]\n'
        + original[original.index("[workspace.package]") :]
    )
    manifest = check.isolated_fee(source, tmp_path / "isolated")
    members = tomllib.loads(manifest.read_text())["workspace"]["members"]
    assert set(members) == {"crates/onlyalpha-kernel/domain", "crates/onlyalpha-kernel/fee"}
