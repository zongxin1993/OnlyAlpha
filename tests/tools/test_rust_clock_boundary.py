"""Clock source closure cannot smuggle native time into deterministic scheduling."""

from pathlib import Path

import pytest

from scripts.rust_kernel_check import validate_clock_sources


def test_pure_clock_rejects_native_and_hidden_source_inputs(tmp_path: Path) -> None:
    source = tmp_path / "crates/onlyalpha-kernel/clock/src/scheduler.rs"
    source.parent.mkdir(parents=True)
    for forbidden in (
        "use std::time::SystemTime;",
        "use std::thread;",
        "fn hidden() {let _ = std::time::UNIX_EPOCH.elapsed();}",
        '#[cfg_attr(all(), path="../../domain/src/lib.rs")] mod hidden;',
        'include!("../../core/src/lib.rs");',
        '#[path="../../core/src/lib.rs"] mod kernel;',
        'const SECRET: &str = env!("HIDDEN_CLOCK_INPUT");',
    ):
        source.write_text(forbidden)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_clock_sources(tmp_path)
    source.write_text("pub struct Timer;\n")
    validate_clock_sources(tmp_path)
