"""观测是基础设施；精确依赖准入不能向纯内核扩散。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.rust_kernel_check import validate_infrastructure_sources, validate_workspace

ROOT = Path(__file__).resolve().parents[2]


class ObservabilityBoundary(unittest.TestCase):
    def test_approved_infrastructure_library_is_admitted(self):
        validate_workspace(ROOT)
        validate_infrastructure_sources(ROOT)

    def test_witness_test_edge_is_exact_and_unknown_paths_remain_rejected(self):
        from scripts.rust_kernel_check import _without_declared_infrastructure_inputs

        target = ROOT / "packages/backend/src/persistence/research_evidence/physical.rs"
        text, modules = _without_declared_infrastructure_inputs(ROOT, target)
        self.assertNotIn('#[path="../../tests/research_evidence_witness.rs"]', text.replace(" ", ""))
        self.assertIn(ROOT / "packages/backend/src/tests/research_evidence_witness.rs", modules)
        original = Path.read_text

        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return value + '\n#[path="../../tests/undeclared.rs"] mod hidden;' if path == target else value

        with patch.object(Path, "read_text", read), self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
            validate_infrastructure_sources(ROOT)

    def test_business_dependency_cannot_enter_observability(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if path == ROOT / "crates/observability/Cargo.toml":
                text = text.replace("[dependencies]", '[dependencies]\nonlyalpha-account = { path = "../account" }')
            return text

        with patch.object(Path, "read_text", read), self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
            validate_workspace(ROOT)

    def test_pure_account_cannot_acquire_observation_dependency(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if path == ROOT / "crates/account/Cargo.toml":
                text = text.replace(
                    "[dependencies]", '[dependencies]\nonlyalpha-observability = { path = "../observability" }'
                )
            return text

        with patch.object(Path, "read_text", read), self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
            validate_workspace(ROOT)


if __name__ == "__main__":
    unittest.main()
