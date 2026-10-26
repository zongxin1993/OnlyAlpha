import shutil
from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_worker_and_protocol_build_as_declared_closures(tmp_path: Path) -> None:
    protocol = check.isolated_gateway_protocol(check.ROOT, tmp_path / "protocol").parent
    assert (protocol / "crates/onlyalpha-gateway-protocol/rust/generated.rs").is_file()
    assert not (protocol / "crates/onlyalpha-kernel").exists()
    assert not (protocol / "packages").exists()
    worker = check.isolated_calculation_bridge(check.ROOT, tmp_path / "worker").parent
    assert (worker / "crates/onlyalpha-kernel/calculation/Cargo.toml").is_file()
    assert (worker / "crates/onlyalpha-kernel/domain/Cargo.toml").is_file()
    assert not (worker / "crates/onlyalpha-kernel/predicates").exists()
    assert not (worker / "src/onlyalpha").exists()


def test_infrastructure_rejects_hidden_source_and_build_inputs(tmp_path: Path) -> None:
    root = check.isolated_http_server(check.ROOT, tmp_path / "source").parent
    for component in ("onlyalpha-runtime-persistence", "onlyalpha-backtest"):
        source = check.ROOT / "crates" / component
        destination = root / "crates" / component
        shutil.copytree(source, destination)
    check.validate_infrastructure_sources(root)
    target = root / "crates/onlyalpha-calculation-bridge/rust/lib.rs"
    target.chmod(0o644)
    original = target.read_text()
    for code in (
        'include!("../../core.rs");',
        '#[path="/tmp/escape.rs"] mod escape;',
        'const X: &str = env!("CONFIG");',
    ):
        target.write_text(code)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_infrastructure_sources(root)
    target.write_text(original)
    manifest = target.parent.parent / "Cargo.toml"
    manifest.chmod(0o644)
    manifest.write_text(manifest.read_text().replace('path = "rust/lib.rs"', 'path = "outside.rs"'))
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_infrastructure_sources(root)
