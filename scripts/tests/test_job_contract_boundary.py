"""作业契约只准入显式单元测试边，不放开隐藏源码／输入。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.rust_kernel_check import _without_declared_infrastructure_inputs, validate_infrastructure_sources

ROOT = Path(__file__).resolve().parents[2]


class JobContractBoundary(unittest.TestCase):
    def test_job_contract_test_edge_is_registered_and_source_is_admitted(self):
        target = ROOT / "packages/backend/src/application/mod.rs"
        text, modules = _without_declared_infrastructure_inputs(ROOT, target)
        self.assertIn(ROOT / "packages/backend/src/tests/job_contract_tests.rs", modules)
        self.assertNotIn("../tests/job_contract_tests.rs", text)
        validate_infrastructure_sources(ROOT)

    def test_neighboring_undeclared_test_and_hidden_input_remain_rejected(self):
        original = Path.read_text
        cases = [
            ("packages/backend/src/application/mod.rs", '#[path="../tests/undeclared_job.rs"] mod hidden;'),
            ("packages/backend/src/application/job_contract.rs", 'include_str!("undeclared-job-input.json");'),
        ]
        for name, injected in cases:
            with self.subTest(name=name):

                def read(path, *args, _name=name, _injected=injected, **kwargs):
                    value = original(path, *args, **kwargs)
                    return value + "\n" + _injected if path == ROOT / _name else value

                with (
                    patch.object(Path, "read_text", read),
                    self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"),
                ):
                    validate_infrastructure_sources(ROOT)
