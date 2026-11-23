"""实际并发区间与缺证处理；不把 wall time 当作 CPU 时间。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.observation_report import legacy_observation_report, load_observation_files, observation_report


def event(kind, span, at, parent=None, **extra):
    return dict(
        schema_version=1,
        event_kind=kind,
        process_instance_id="p1",
        pid=10,
        trace_id="trace",
        span_id=span,
        parent_span_id=parent,
        mono_ns=at,
        module="runtime",
        operation="read",
        **extra,
    )


def pair(span, start, end, parent=None, **extra):
    return [
        event("operation_start", span, start, parent, **extra),
        event(
            "operation_end",
            span,
            end,
            parent,
            start_mono_ns=start,
            end_mono_ns=end,
            duration_ns=end - start,
            outcome="ok",
            **extra,
        ),
    ]


class ObservationReportTests(unittest.TestCase):
    def test_witness_failure_summary_retains_only_explicit_primitive_details(self):
        row = event(
            "summary",
            "root",
            10,
            outcome="failed",
            error_code="WITNESS_SIZE_MISMATCH",
            file_path="/retained/" + "x" * 300 + "/manifest.json",
            expected_value="123",
            actual_value="124",
        )
        row["operation"] = "evidence.witness.failure"
        try:
            report = observation_report([row])
        except ValueError:
            report = None
        self.assertIsNotNone(report, "approved Witness diagnostic fields were rejected")
        self.assertEqual(report["summaries"][0]["file_path"], row["file_path"])
        self.assertEqual(report["summaries"][0]["expected_value"], "123")
        with self.assertRaises(ValueError):
            observation_report([dict(row, actual_value={"payload": "secret"})])
        for change in (
            {"file_path": ""},
            {"file_path": "x" * 4097},
            {"expected_value": None},
            {"actual_value": "x" * 257},
            {"outcome": "ok"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                observation_report([row | change])

    def test_flow_report_cli_accepts_versioned_observation_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "trace.jsonl", Path(directory) / "report.json"
            rows = pair("root", 0, 100, run_id="run")
            rows.append(
                dict(
                    schema_version=1,
                    event_kind="session_end",
                    process_instance_id="p1",
                    pid=10,
                    mono_ns=101,
                    shutdown_complete=True,
                    dropped_events=0,
                    io_errors=0,
                )
            )
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.backtest_benchmark",
                    "--observations",
                    str(path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(output.read_text())["observations"]
            self.assertTrue(saved["complete"])
            self.assertEqual(saved["runs"]["run"]["roots"][0]["duration_ns"], 100)

    def test_jsonl_reader_requires_close_receipt_and_retains_truncated_stream_as_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.jsonl"
            rows = pair("root", 0, 100)
            rows.append(
                dict(
                    schema_version=1,
                    event_kind="session_end",
                    process_instance_id="p1",
                    pid=10,
                    mono_ns=101,
                    shutdown_complete=True,
                    dropped_events=0,
                    io_errors=0,
                )
            )
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            self.assertTrue(load_observation_files([path])["complete"])
            path.write_text(path.read_text() + '{"event_kind":')
            report = load_observation_files([path])
            self.assertFalse(report["complete"])
            self.assertEqual(report["operations"][0]["duration_ns"], 100)
            self.assertIsNone(report["operations"][0]["uncovered_ns"])
            self.assertEqual(report["read_errors"][0]["code"], "DIAGNOSTIC_JSON_INVALID")

    def test_end_cannot_reassign_or_drop_immutable_operation_associations(self):
        original = dict(run_id="run-a", command_id="command-a", request_id="request-a", attempt=1, links="original")
        for field in ("pid", *original):
            for mode in ("changed", "missing", "added"):
                rows = pair("root", 0, 100, **original)
                if mode == "missing":
                    rows[1].pop(field, None)
                elif mode == "added":
                    rows[0].pop(field, None)
                else:
                    rows[1][field] = 2 if field in ("pid", "attempt") else "other"
                with self.subTest(field=field, mode=mode), self.assertRaisesRegex(ValueError, "identity"):
                    observation_report(rows)

    def test_overlapping_children_use_union_and_resource_holds_are_not_compute(self):
        rows = pair("parent", 0, 100) + pair("a", 10, 60, "parent") + pair("b", 40, 80, "parent")
        resource = pair("lock", 0, 100, "parent", lock_type="shared")
        for row in resource:
            row["operation"] = "generation.hold"
        rows += resource
        report = observation_report(rows)
        parent = next(r for r in report["operations"] if r["span_id"] == "parent")
        self.assertEqual(parent["uncovered_ns"], 30)
        self.assertEqual(parent["child_union_ns"], 70)
        self.assertTrue(report["complete"])

    def test_lock_attempt_is_wait_work_and_is_included_in_parent_child_union(self):
        rows = pair("parent", 0, 100) + pair("attempt", 10, 40, "parent", lock_type="exclusive")
        for row in rows[2:]:
            row["operation"] = "generation.lock_attempt"
        report = observation_report(rows)
        self.assertEqual(report["operations"][0]["uncovered_ns"], 70)

    def test_missing_end_and_loss_invalidate_parent_uncovered_claim(self):
        for suffix in (
            [event("operation_start", "child", 10, "parent")],
            [event("diagnostic_loss", "loss", 50, dropped_events=1)],
        ):
            with self.subTest(suffix=suffix):
                report = observation_report(pair("parent", 0, 100) + suffix)
                self.assertFalse(report["complete"])
                self.assertIsNone(report["operations"][0]["uncovered_ns"])

    def test_missing_parent_cross_process_parent_and_missing_session_end_are_unknown(self):
        rows = pair("child", 10, 60, "absent")
        report = observation_report(rows, require_session_end=True)
        self.assertFalse(report["complete"])
        self.assertIsNone(report["operations"][0]["uncovered_ns"])
        self.assertIn("missing_session_end:p1", report["incomplete"])
        rows = pair("parent", 0, 100)
        rows += [{**row, "process_instance_id": "p2"} for row in pair("child", 0, 20, "parent")]
        self.assertFalse(observation_report(rows)["complete"])

    def test_explicit_end_does_not_wait_for_span_handle_and_preserves_failed_outcome(self):
        report = observation_report(pair("a", 5, 25, error_code="denied"))
        self.assertEqual(report["operations"][0]["duration_ns"], 20)
        self.assertEqual(report["operations"][0]["error_code"], "denied")

    def test_invalid_schema_leaked_fields_duplicate_or_reversed_intervals_are_rejected(self):
        cases = [
            pair("a", 0, 10) + pair("a", 20, 30),
            [{**event("operation_start", "a", 0), "schema_version": 2}],
            [{**event("operation_start", "a", 0), "request_body": "secret"}],
            pair("a", 20, 10),
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                observation_report(rows)

    def test_legacy_logs_keep_duration_but_cannot_claim_async_or_restart_causality(self):
        lines = [
            'BACKTEST_PROFILE {"event":"begin","pid":1,"id":2,"parent":null,"run":"r","stage":"read"}',
            'BACKTEST_PROFILE {"event":"end","pid":1,"id":2,"elapsed_ns":"50","ok":true}',
        ]
        report = legacy_observation_report(lines)
        self.assertFalse(report["complete"])
        self.assertEqual(report["operations"][0]["duration_ns"], 50)
        self.assertIsNone(report["operations"][0]["uncovered_ns"])
        self.assertIsNone(report["operations"][0]["process_instance_id"])

    def test_child_outside_parent_invalidates_all_ancestor_uncovered_claims(self):
        report = observation_report(
            pair("root", 0, 100) + pair("parent", 10, 50, "root") + pair("child", 20, 80, "parent")
        )
        self.assertFalse(report["complete"])
        self.assertIsNone(report["operations"][0]["uncovered_ns"])

    def test_typed_schema_refuses_boolean_counters_and_non_string_associations(self):
        for update in ({"schema_version": True}, {"trace_id": 1}, {"work_items": -1}, {"bytes": True}):
            rows = pair("root", 0, 1)
            rows[0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                observation_report(rows)


if __name__ == "__main__":
    unittest.main()


class FlowSummary(unittest.TestCase):
    def test_hotspots_keep_inclusive_call_cost_separate_from_root_wall_coverage(self):
        from scripts.observation_report import flow_summary

        rows = (
            pair("root", 0, 100, run_id="run")
            + pair("a", 10, 60, "root", run_id="run", work_items=3, bytes=30)
            + pair("b", 40, 80, "root", run_id="run", work_items=4, bytes=40)
        )
        report = observation_report(rows)
        summary = flow_summary(report, "run")
        self.assertEqual(summary["roots"][0]["duration_ns"], 100)
        self.assertEqual(summary["roots"][0]["uncovered_ns"], 30)
        self.assertEqual(summary["hotspots"][0]["observed_calls"], 3)
        self.assertEqual(summary["hotspots"][0]["inclusive_call_duration_sum_ns"], 190)
        self.assertEqual(summary["hotspots"][0]["work_items_observed"], 7)
        self.assertFalse(summary["inclusive_call_totals_are_flow_latency"])

    def test_missing_close_keeps_durations_as_observed_lower_bound_and_residual_unknown(self):
        from scripts.observation_report import flow_summary

        report = observation_report(pair("root", 0, 100, run_id="run"), require_session_end=True)
        summary = flow_summary(report, "run")
        self.assertFalse(summary["complete"])
        self.assertIsNone(summary["roots"][0]["uncovered_ns"])
        self.assertEqual(summary["hotspots"][0]["closed_durations_observed"], 1)
        self.assertEqual(summary["hotspots"][0]["coverage_complete_calls"], 0)
        self.assertEqual(summary["critical_path"]["status"], "dependency_not_proven")

    def test_abandoned_root_keeps_its_actual_start_and_unknown_end(self):
        from scripts.observation_report import flow_summary

        rows = pair("finished", 0, 20, run_id="run") + [event("operation_start", "interrupted", 30, run_id="run")]
        summary = flow_summary(observation_report(rows), "run")
        self.assertEqual([r["start_mono_ns"] for r in summary["roots"]], [0, 30])
        self.assertIsNone(summary["roots"][1]["end_mono_ns"])
        self.assertIsNone(summary["roots"][1]["uncovered_ns"])

    def test_queue_and_http_status_summaries_remain_available_without_counting_as_calls(self):
        rows = pair("root", 0, 100, run_id="run")
        queued = event("summary", "root", 5, run_id="run", command_id="command", outcome="queued")
        queued["operation"] = "backtest.run.queued"
        rows.append(queued)
        report = observation_report(rows)
        self.assertEqual(report["summaries"], [queued])
        self.assertEqual(len(report["operations"]), 1)
