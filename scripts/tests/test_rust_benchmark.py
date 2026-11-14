import tempfile
import unittest
from pathlib import Path

from scripts.rust_benchmark import (
    benchmark_input_identity,
    compare_report_sets,
    compare_reports,
    criterion_reports,
    criterion_samples,
    legacy_reports,
    result_identity,
    retained_reports,
    storage_conditions,
    validate_complete_trace,
    validate_fixture_provenance,
    validate_inventory,
)

STORAGE = storage_conditions("1 0 0:1 / / rw - overlay overlay rw\n", {"temporary": "/tmp"})


class BenchmarkContracts(unittest.TestCase):
    def test_missing_entry_and_placeholder_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = dict(crate="account", target="recovery", operation="restore", unit="records", sizes=[64, 129, 326])
            with self.assertRaisesRegex(ValueError, "missing"):
                validate_inventory(root, [case])
            (root / "crates/account/benches").mkdir(parents=True)
            (root / "crates/account/benches/recovery.rs").write_text("fn main() {}")
            (root / "crates/account/BENCHMARK.md").write_text("placeholder")
            with self.assertRaisesRegex(ValueError, "benchmark"):
                validate_inventory(root, [case])
            (root / "crates/account/benches/recovery.rs").write_text("BENCHMARK_SAMPLE")
            retained = dict(case, sizes=[1481], external_input="OA_BENCH_RUNTIME", rounds=3)
            validate_inventory(root, [retained])

    def test_comparison_requires_equal_work_and_output(self):
        base = dict(
            schema_version=1,
            case="restore",
            input_sha256="a",
            result_sha256="b",
            environment={"storage": STORAGE},
            unit="records",
            work_items=326,
            samples_ns=[100, 110, 120],
        )
        changed = dict(base, samples_ns=[110, 121, 132])
        self.assertAlmostEqual(compare_reports(changed, base)["median_ratio"], 1.1)
        with self.assertRaisesRegex(ValueError, "result_sha256"):
            compare_reports(dict(changed, result_sha256="wrong"), base)
        with self.assertRaisesRegex(ValueError, "samples"):
            compare_reports(dict(changed, samples_ns=[]), base)

    def test_missing_storage_evidence_cannot_produce_a_comparison(self):
        report = dict(
            schema_version=1,
            case="runtime",
            input_sha256="i",
            result_sha256="r",
            environment={"cache": "warm"},
            unit="rows",
            work_items=1,
            samples_ns=[1, 2, 3],
        )
        with self.assertRaisesRegex(ValueError, "storage"):
            compare_reports(report, report)

    def test_retained_comparison_requires_the_actual_input_storage_role(self):
        report = dict(
            schema_version=1,
            case="runtime/retained/source.read",
            input_sha256="i",
            result_sha256="r",
            environment={"storage": STORAGE},
            unit="rows",
            work_items=1,
            samples_ns=[1, 2, 3],
        )
        with self.assertRaisesRegex(ValueError, "storage"):
            compare_reports(report, report)

    def test_storage_description_tracks_selected_mount_without_container_layer_ids(self):
        from scripts.rust_benchmark import storage_conditions

        mounts = "1 0 0:1 / / rw - overlay overlay rw,lowerdir=/layers/old,upperdir=/old/upper,workdir=/old/work\n2 1 0:2 /Users/work/test-results /workspace/test-results rw - virtiofs hostshare rw\n"
        locations = {"temporary": "/tmp/bench-1", "retained_input": "/workspace/test-results/run/runtime"}
        first = storage_conditions(mounts, locations)
        second = storage_conditions(mounts.replace("/old", "/new").replace("/layers/old", "/layers/new"), locations)
        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            storage_conditions(mounts.replace("/Users/work/test-results", "/Volumes/other/test-results"), locations),
        )
        self.assertNotEqual(first, storage_conditions(mounts.splitlines()[0], locations))
        with self.assertRaisesRegex(ValueError, "storage"):
            storage_conditions("", locations)
        report = dict(
            schema_version=1,
            case="runtime",
            input_sha256="i",
            result_sha256="r",
            environment={"storage": first},
            unit="rows",
            work_items=1,
            samples_ns=[1, 2, 3],
        )
        other = dict(
            report,
            environment={
                "storage": storage_conditions(
                    mounts.replace("/Users/work/test-results", "/Volumes/other/test-results"), locations
                )
            },
        )
        with self.assertRaisesRegex(ValueError, "environment"):
            compare_reports(report, other)
        self.assertEqual(compare_reports(report, report)["median_ratio"], 1)

    def test_criterion_samples_are_per_iteration_and_complete(self):
        data = {"iters": [1, 2, 4], "times": [100, 220, 480], "sampling_mode": "Linear"}
        self.assertEqual(criterion_samples(data), [100, 110, 120])
        for invalid in (
            {**data, "times": [100]},
            {**data, "iters": [1, 0, 4]},
            {**data, "times": [100, float("nan"), 480]},
        ):
            with self.assertRaises(ValueError):
                criterion_samples(invalid)

    def test_result_identity_requires_unique_preflight_outputs(self):
        self.assertEqual(
            result_identity("BENCHMARK_RESULT small a\nBENCHMARK_RESULT large b"),
            result_identity("BENCHMARK_RESULT large b\nBENCHMARK_RESULT small a"),
        )
        for value in ("no assertions", "BENCHMARK_RESULT small a\nBENCHMARK_RESULT small b"):
            with self.assertRaises(ValueError):
                result_identity(value)

    def test_report_separates_build_from_comparison_environment(self):
        sample = dict(
            case={"full_id": "restore/small", "throughput": {"Bytes": 12}},
            samples_ns=[100, 110, 120],
            criterion_estimates={},
        )
        metadata = dict(
            preflight="passed all source assertions",
            measurement="complete",
            case={"crate": "account", "target": "recovery"},
            input_sha256="i",
            result_sha256="r",
            compiler="rust",
            platform={"system": "Linux", "machine": "aarch64"},
            profile="bench",
            features="default",
            cache="warm",
            hardware={"cores": 2},
            storage=STORAGE,
            source={"digest": "s"},
            binary_sha256="b",
        )
        report = criterion_reports([sample], metadata)[0]
        self.assertEqual(report["work_items"], 12)
        self.assertEqual(report["unit"], "bytes")
        self.assertEqual(report["build"]["binary_sha256"], "b")
        self.assertNotIn("source", report["environment"])
        self.assertEqual(report["environment"]["storage"], STORAGE)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            criterion_reports([sample], dict(metadata, measurement="not run"))

    def test_provenance_requires_actual_frozen_bytes(self):
        import hashlib
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.json").write_bytes(b"{}")
            (root / "provenance.json").write_text(
                json.dumps({"files": {"input.json": hashlib.sha256(b"{}").hexdigest()}})
            )
            validate_fixture_provenance(root)
            (root / "input.json").write_bytes(b'{"changed":true}')
            with self.assertRaisesRegex(ValueError, "fixture"):
                validate_fixture_provenance(root)

    def test_comparison_rejects_nonfinite_samples_and_missing_cases(self):
        base = dict(
            schema_version=1,
            case="test",
            input_sha256="i",
            result_sha256="r",
            environment={"storage": STORAGE},
            unit="bytes",
            work_items=1,
            samples_ns=[1, 2, 3],
        )
        with self.assertRaises(ValueError):
            compare_reports(dict(base, samples_ns=[1, float("nan"), 3]), base)
        with self.assertRaises(ValueError):
            compare_report_sets([base], [])
        with self.assertRaises(ValueError):
            compare_report_sets([base, base], [base])
        self.assertEqual(compare_report_sets([base], [base])["test"]["median_ratio"], 1)

    def test_retained_reports_require_every_round_stage_and_same_result(self):
        import json

        metadata = dict(
            case={
                "crate": "runtime",
                "target": "retained",
                "rounds": 3,
                "sizes": [1481],
                "stages": ["source.read", "source.verify_cut"],
            },
            input_sha256="i",
            compiler="rust",
            platform={},
            profile="bench",
            features="default",
            cache="hashed input; no eviction",
            hardware={},
            source={"cut": "s"},
            binary_sha256="current executable",
        )
        lines = []
        for n in range(1, 4):
            for stage in metadata["case"]["stages"]:
                lines.append(
                    "BENCHMARK_SAMPLE "
                    + json.dumps(
                        dict(schema_version=1, crate="onlyalpha-runtime", round=n, stage=stage, elapsed_ns=str(100 * n))
                    )
                )
            lines.append("BENCHMARK_RESULT " + str(n) + " " + "a" * 64)
        report = retained_reports("\n".join(lines), metadata)
        self.assertEqual(report[0]["samples_ns"], [100, 200, 300])
        self.assertEqual(report[0]["build"]["binary_sha256"], "current executable")
        for broken in (
            lines[:-1],
            lines + [lines[0]],
            [line.replace("a" * 64, "b" * 64) if line.startswith("BENCHMARK_RESULT 3 ") else line for line in lines],
        ):
            with self.assertRaises(ValueError):
                retained_reports("\n".join(broken), metadata)

    def test_legacy_chain_cannot_use_historical_artifact_as_current_binary(self):
        import json

        meta = dict(
            rounds=3, stage_count=2, benchmark_binary_sha256="current", compiler="rust", os="linux", arch="aarch64"
        )
        lines = ["BACKTEST_BENCHMARK_META " + json.dumps(meta)]
        for n in range(1, 4):
            for stage in ("read", "chain.total"):
                lines.append(
                    "BACKTEST_BENCHMARK "
                    + json.dumps(dict(round=n, stage=stage, elapsed_ns="100", result_sha256="same-result"))
                )
        metadata = dict(
            case={"crate": "backend", "target": "backtest_chain", "unit": "chains", "sizes": [1]},
            input_sha256="i",
            compiler="rust",
            platform={},
            profile="bench",
            features="default",
            cache="warm",
            hardware={},
            source={},
            binary_sha256="current",
        )
        self.assertEqual(len(legacy_reports("\n".join(lines), metadata)), 2)
        with self.assertRaisesRegex(ValueError, "binary"):
            legacy_reports("\n".join(lines), dict(metadata, binary_sha256="historical kernel"))

    def test_header_extract_cannot_replace_original_complete_trace(self):
        import json

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trace.json"
            fixture = {"binding": {"work": "original"}, "inputs": {"records": []}}
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "complete trace"):
                validate_complete_trace(path, fixture)
            full = dict(fixture, schema_version=2, kind="controlled", state={}, steps=[])
            path.write_text(json.dumps(full))
            self.assertEqual(len(validate_complete_trace(path, fixture)), 64)
            with self.assertRaisesRegex(ValueError, "binding"):
                validate_complete_trace(path, dict(fixture, binding={"work": "foreign"}))

    def test_input_identity_binds_harness_and_fixtures_but_allows_library_changes(self):
        case = {"crate": "account", "target": "recovery"}
        paths = {
            "crates/account/benches/recovery.rs": "a" * 64,
            **{"test-data/backtest-benchmarks/" + name + ".json": "b" * 64 for name in ["small", "medium", "large"]},
            "crates/account/src/manager.rs": "c" * 64,
        }
        original = benchmark_input_identity(paths, case)
        self.assertEqual(
            original, benchmark_input_identity(dict(paths, **{"crates/account/src/manager.rs": "d" * 64}), case)
        )
        for name in ["crates/account/benches/recovery.rs", "test-data/backtest-benchmarks/small.json"]:
            self.assertNotEqual(original, benchmark_input_identity(dict(paths, **{name: "d" * 64}), case))
        with self.assertRaises(ValueError):
            benchmark_input_identity({}, case)


if __name__ == "__main__":
    unittest.main()
