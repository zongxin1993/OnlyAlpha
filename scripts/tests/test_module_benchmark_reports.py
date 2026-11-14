import json
import tempfile
import unittest
from pathlib import Path

from scripts.backtest_benchmark import module_reports
from scripts.rust_benchmark import storage_conditions

STORAGE = storage_conditions("1 0 0:1 / / rw - overlay overlay rw\n", {"temporary": "/tmp"})


class ModuleReports(unittest.TestCase):
    def test_case_sets_are_validated_before_joining_flow_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            row = dict(
                schema_version=1,
                case="account/recovery/restore",
                input_sha256="input",
                result_sha256="result",
                environment={"storage": STORAGE},
                unit="bytes",
                work_items=12,
                samples_ns=[1, 2, 3],
            )
            path.write_text(json.dumps([row]))
            self.assertEqual(module_reports([path]), [row])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                module_reports([path, path])
            path.write_text(json.dumps([dict(row, samples_ns=[1])]))
            with self.assertRaisesRegex(ValueError, "samples"):
                module_reports([path])


if __name__ == "__main__":
    unittest.main()
