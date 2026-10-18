from pathlib import Path

import pytest

from scripts.rust_kernel_check import validate_event_sources


def test_event_rejects_native_effects_and_hidden_inputs(tmp_path: Path) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/event/src/bus.rs"
    source.parent.mkdir(parents=True)
    for forbidden in (
        "use std::time::SystemTime;",
        "use std::thread;",
        "use std::fs::File;",
        "use std::process::Command;",
        "use std::net::TcpStream;",
        'fn ambient() { std::env::var("EVENT_CONFIG"); }',
        "fn hidden() { let _ = std::time::UNIX_EPOCH.elapsed(); }",
        '#[cfg_attr(all(), path="../../core/src/lib.rs")] mod hidden;',
        'include!("../../clock/src/lib.rs");',
        'const CONFIG: &str = env!("HIDDEN_EVENT_INPUT");',
        "fn identity() { uuid::Uuid::new_v4(); }",
    ):
        source.write_text(forbidden)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_event_sources(tmp_path)
    source.write_text("//! Single-thread observer, with no OS effects.\npub struct Event;\n")
    validate_event_sources(tmp_path)


def test_event_isolated_closure_excludes_other_kernel_and_runtime(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT, isolated_event

    manifest = isolated_event(ROOT, tmp_path / "isolated")
    root = manifest.parent
    assert set(tomllib.loads(manifest.read_text())["workspace"]["members"]) == {
        "crates/onlyalpha-kernel/domain",
        "crates/onlyalpha-kernel/event",
    }
    for forbidden in (
        "crates/onlyalpha-kernel/core",
        "crates/onlyalpha-kernel/clock",
        "src/onlyalpha",
        "packages",
        "plugs",
    ):
        assert not (root / forbidden).exists()
