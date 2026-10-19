"""Broker semantic isolation and actual Virtual Broker comparison inputs."""

from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_broker_is_an_independent_domain_only_closure(tmp_path: Path) -> None:
    check.validate_broker_sources(check.ROOT)
    isolated = check.isolated_broker(check.ROOT, tmp_path / "isolated").parent
    assert (isolated / "crates/onlyalpha-kernel/broker/Cargo.toml").is_file()
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
def test_broker_rejects_io_and_reverse_authority_edges(tmp_path: Path, code: str) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/broker/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text(code)
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_broker_sources(tmp_path)


def test_real_virtual_broker_trace_has_session_independent_canonical_facts() -> None:
    from scripts.broker_reference_check import check_fixture, virtual_corpus

    check_fixture()
    cases = virtual_corpus()
    assert [case["fact"]["kind"] for case in cases[:3]] == ["ACCEPTED", "TRADE", "CANCELLED"]
    assert cases[1]["fact"]["payload"]["fill"]["quantity"]["value"] == "40"
    for first, repeated in zip(cases[:3], cases[3:6], strict=True):
        assert first["identity"] == repeated["identity"]
        assert first["fingerprint"] == repeated["fingerprint"]
    assert cases[0]["identity"] == "EACK-1d177748ed31986c8f5d681f8943d57159623069dc3293aac25fb087503aa34d"
    assert cases[0]["fingerprint"] == "a8b6f3f24b3f3bdbf703b8f1be86b893e303a639c4cefab81218b9fc5cf37580"
