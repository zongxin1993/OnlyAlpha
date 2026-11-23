"""观测开销对照必须显式选择同一真实 Runtime harness。"""

import unittest

from scripts.run_rust_benchmarks import select_benchmarks
from scripts.rust_benchmark import storage_conditions

STORAGE = storage_conditions(
    "1 0 0:1 / / rw - overlay overlay rw\n", {"temporary": "/tmp", "retained_input": "/workspace/test-results/runtime"}
)


class BenchmarkObservation(unittest.TestCase):
    def test_detail_only_admits_explicit_runtime_retained_target(self):
        rows = [
            {"crate": "runtime", "target": "recovery"},
            {"crate": "runtime", "target": "retained"},
            {"crate": "account", "target": "recovery"},
        ]
        self.assertEqual(select_benchmarks(rows, ["runtime"], ["retained"], "detail"), [rows[1]])
        self.assertEqual(select_benchmarks(rows, ["runtime"], [], "off"), rows[:2])
        for crates, targets, mode in [
            (["runtime"], [], "detail"),
            (["account"], [], "detail"),
            (["runtime"], ["missing"], "off"),
            ([], [], "unknown"),
        ]:
            with self.subTest(crates=crates, targets=targets, mode=mode), self.assertRaises(ValueError):
                select_benchmarks(rows, crates, targets, mode)

    def test_missing_wrong_mode_or_lossy_close_cannot_certify_overhead_samples(self):
        import json

        from scripts.rust_benchmark import diagnostic_receipt

        close = dict(schema_version=1, event_kind="session_end", shutdown_complete=True, dropped_events=0, io_errors=0)

        def line(mode, row):
            return "BENCHMARK_DIAGNOSTICS " + json.dumps(dict(mode=mode, receipt=row))

        self.assertEqual(diagnostic_receipt(line("detail", close), "detail"), close)
        for log in [
            "",
            line("off", close),
            line("detail", dict(close, dropped_events=1)),
            line("detail", dict(close, shutdown_complete=False)),
            line("detail", close) + "\n" + line("detail", close),
        ]:
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, "incomplete benchmark diagnostics"):
                diagnostic_receipt(log, "detail")

    def test_overhead_comparison_requires_same_binary_inputs_and_complete_receipts(self):
        from scripts.rust_benchmark import compare_observation_overhead, compare_reports

        close = dict(shutdown_complete=True, dropped_events=0, io_errors=0)
        off = dict(
            schema_version=1,
            case="runtime/retained/source.read",
            input_sha256="input",
            result_sha256="result",
            environment={"platform": "fixed", "storage": STORAGE},
            build={"source": "same", "binary_sha256": "binary"},
            unit="records",
            work_items=326,
            samples_ns=[100, 110, 120],
            diagnostics_receipt=close,
        )
        detail = dict(
            off,
            environment={"platform": "fixed", "storage": STORAGE, "diagnostics_mode": "detail"},
            samples_ns=[110, 121, 132],
        )
        with self.assertRaisesRegex(ValueError, "environment"):
            compare_reports(detail, off)
        self.assertAlmostEqual(compare_observation_overhead([off], [detail])["cases"][off["case"]]["median_ratio"], 1.1)
        for changed in [
            dict(detail, build={"source": "changed", "binary_sha256": "binary"}),
            dict(detail, diagnostics_receipt=dict(close, dropped_events=1)),
            dict(detail, input_sha256="other"),
            dict(detail, result_sha256="other"),
            dict(detail, samples_ns=[1]),
        ]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                compare_observation_overhead([off], [changed])
        self.assertEqual(detail["environment"]["diagnostics_mode"], "detail")

    def test_boolean_criterion_numbers_cannot_become_throughput(self):
        from scripts.rust_benchmark import criterion_samples

        for field in ("iters", "times"):
            row = {"iters": [1, 2, 3], "times": [100, 200, 300]}
            row[field][1] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                criterion_samples(row)
