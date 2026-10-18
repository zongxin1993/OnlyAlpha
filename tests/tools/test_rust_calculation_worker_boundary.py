import shutil
from pathlib import Path

import pytest

from scripts import rust_kernel_check as check


def test_worker_and_protocol_build_as_declared_closures(tmp_path: Path) -> None:
    protocol = check.isolated_gateway_protocol(check.ROOT, tmp_path / "protocol").parent
    assert (protocol / "packages/onlyalpha-gateway-protocol/rust/generated.rs").is_file()
    assert not (protocol / "crates").exists()
    worker = check.isolated_calculation_worker(check.ROOT, tmp_path / "worker").parent
    assert (worker / "crates/onlyalpha-kernel/calculation/Cargo.toml").is_file()
    assert (worker / "crates/onlyalpha-kernel/domain/Cargo.toml").is_file()
    assert not (worker / "crates/onlyalpha-kernel/core").exists()
    assert not (worker / "src/onlyalpha").exists()


def test_infrastructure_rejects_hidden_source_and_build_inputs(tmp_path: Path) -> None:
    for component in ("onlyalpha-gateway-protocol", "onlyalpha-calculation-worker"):
        source = check.ROOT / "packages" / component
        destination = tmp_path / "packages" / component
        shutil.copytree(source, destination)
    check.validate_infrastructure_sources(tmp_path)
    target = tmp_path / "packages/onlyalpha-calculation-worker/rust/lib.rs"
    target.chmod(0o644)
    original = target.read_text()
    for code in (
        'include!("../../core.rs");',
        '#[path="/tmp/escape.rs"] mod escape;',
        'const X: &str = env!("CONFIG");',
    ):
        target.write_text(code)
        with pytest.raises(ValueError, match="BOUNDARY"):
            check.validate_infrastructure_sources(tmp_path)
    target.write_text(original)
    manifest = target.parent.parent / "Cargo.toml"
    manifest.chmod(0o644)
    manifest.write_text(manifest.read_text().replace('path = "rust/lib.rs"', 'path = "outside.rs"'))
    with pytest.raises(ValueError, match="BOUNDARY"):
        check.validate_infrastructure_sources(tmp_path)
