"""只有登记的 Cargo bench 可以读取登记的技术输入，不能放宽生产纯性。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.rust_kernel_check import validate_account_sources, validate_benchmark_sources

ROOT = Path(__file__).resolve().parents[2]


class BenchmarkSources(unittest.TestCase):
    def test_current_benches_have_declared_inputs(self):
        validate_benchmark_sources(ROOT)

    def test_bench_cannot_include_undeclared_fixture(self):
        original = Path.read_text
        target = ROOT / "crates/domain/benches/workload.rs"

        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return value + '\nconst HIDDEN:&str=include_str!("/etc/passwd");' if path == target else value

        with patch.object(Path, "read_text", read):
            with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                validate_benchmark_sources(ROOT)

    def test_cargo_cannot_redirect_to_unchecked_benchmark_source(self):
        original = Path.read_text
        target = ROOT / "crates/account/Cargo.toml"

        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return (
                value + '\n[[bench]]\nname="rogue"\npath="unchecked.txt"\nharness=false\n' if path == target else value
            )

        with patch.object(Path, "read_text", read):
            with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                validate_benchmark_sources(ROOT)

    def test_production_cannot_import_bench_or_read_clock(self):
        original = Path.read_text
        target = ROOT / "crates/account/src/lib.rs"
        for extra in ("\nuse std::time::Instant;", '\n#[path="../benches/recovery.rs"] mod hidden;'):

            def read(path, *args, extra=extra, **kwargs):
                value = original(path, *args, **kwargs)
                return value + extra if path == target else value

            with patch.object(Path, "read_text", read):
                with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                    validate_account_sources(ROOT)


if __name__ == "__main__":
    unittest.main()
