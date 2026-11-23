"""基准依赖可用于显式 dev 入口，不能流入生产内核。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.rust_kernel_check import validate_workspace

ROOT = Path(__file__).resolve().parents[2]


class BenchmarkDependencies(unittest.TestCase):
    def test_approved_benchmark_manifests(self):
        validate_workspace(ROOT)

    def test_criterion_cannot_become_production_dependency(self):
        original = Path.read_text
        target = ROOT / "crates/account/Cargo.toml"

        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == target:
                value = value.replace("[dependencies]", "[dependencies]\ncriterion = { workspace = true }")
            return value

        with patch.object(Path, "read_text", read):
            with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                validate_workspace(ROOT)

    def test_workspace_criterion_features_cannot_drift(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == ROOT / "Cargo.toml":
                value = value.replace("cargo_bench_support", "html_reports")
            return value

        with patch.object(Path, "read_text", read):
            with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                validate_workspace(ROOT)


if __name__ == "__main__":
    unittest.main()
