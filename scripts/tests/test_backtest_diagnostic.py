"""单次 Web 取证协调器只观察，不写业务事实。"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.backtest_diagnostic import observe_sql, read_control_events


class DiagnosticControl(unittest.TestCase):
    def test_cursor_retains_partial_line_and_filters_bulk_child_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            wanted = dict(
                schema_version=1,
                event_kind="lock_acquired",
                operation="generation.hold",
                run_id="run",
                process_instance_id="process",
                span_id="7",
                lock_type="shared",
            )
            bulk = dict(schema_version=1, event_kind="operation_end", operation="source.read")
            raw = (json.dumps(wanted) + "\n" + json.dumps(bulk) + "\n").encode()
            path.write_bytes(raw + b'{"schema_')
            first = read_control_events(path, 0)
            self.assertEqual(first, {"cursor": len(raw), "events": [wanted]})
            with path.open("ab") as stream:
                stream.write(b'version":1,"event_kind":"session_start"}\n')
            second = read_control_events(path, first["cursor"])
            self.assertEqual(second["events"], [dict(schema_version=1, event_kind="session_start")])
            self.assertEqual(second["cursor"], path.stat().st_size)

    def test_truncation_or_payload_leak_is_rejected_without_echoing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"schema_version":1,"password":"private"}\n')
            with self.assertRaisesRegex(ValueError, "DIAGNOSTIC_EVENT_INVALID") as error:
                read_control_events(path, 0)
            self.assertNotIn("private", str(error.exception))
            with self.assertRaisesRegex(ValueError, "DIAGNOSTIC_CURSOR_INVALID"):
                read_control_events(path, 999)

    def test_sql_observation_binds_both_namespace_and_exact_original_run(self):
        class Connection:
            def __init__(self, rows):
                self.rows = iter(rows)
                self.calls = []

            def execute(self, sql, parameters=()):
                self.calls.append((sql, parameters))
                self.current = next(self.rows)
                return self

            def fetchone(self):
                return self.current

        connection = Connection([("namespace",), ("COMPLETED", True, "namespace")])
        self.assertEqual(observe_sql(connection, "run", "namespace"), {"state": "COMPLETED", "finished": True})
        self.assertEqual(connection.calls[1][1], ("run",))
        self.assertTrue(all(call[0].startswith("SELECT ") for call in connection.calls))
        with self.assertRaisesRegex(ValueError, "DIAGNOSTIC_NAMESPACE_MISMATCH"):
            observe_sql(Connection([("foreign",)]), "run", "namespace")
        self.assertEqual(observe_sql(Connection([("namespace",), None]), "run", "namespace")["state"], "unknown")
        with self.assertRaisesRegex(ValueError, "DIAGNOSTIC_NAMESPACE_MISMATCH"):
            observe_sql(Connection([("namespace",), ("COMPLETED", True, "foreign")]), "run", "namespace")


class DiagnosticBrowserBudget(unittest.TestCase):
    def test_budget_terminates_only_its_own_browser_process_group(self):
        import signal
        import subprocess
        from unittest.mock import Mock, patch

        from scripts.backtest_diagnostic import run_browser

        child = Mock(pid=123)
        child.wait.side_effect = [subprocess.TimeoutExpired(["browser"], 1160), 0]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("scripts.backtest_diagnostic.subprocess.Popen", return_value=child) as create,
            patch("scripts.backtest_diagnostic.os.killpg") as kill,
        ):
            result = run_browser(["browser"], cwd=Path(directory), env={}, receipt=Path(directory) / "budget.json")
            self.assertEqual(result, 124)
            self.assertTrue(create.call_args.kwargs["start_new_session"])
            self.assertEqual(child.wait.call_args_list[0].kwargs, {"timeout": 1160})
            kill.assert_called_once_with(123, signal.SIGTERM)
            row = json.loads((Path(directory) / "budget.json").read_text())
            self.assertTrue(row["budget_exhausted"])
            self.assertEqual(row["browser_budget_seconds"], 1160)

    def test_interruption_closes_owned_browser_group_and_preserves_original_error(self):
        import signal
        from unittest.mock import Mock, patch

        from scripts.backtest_diagnostic import run_browser

        child = Mock(pid=124)
        child.wait.side_effect = [InterruptedError("original interruption"), 0]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("scripts.backtest_diagnostic.subprocess.Popen", return_value=child),
            patch("scripts.backtest_diagnostic.os.killpg") as kill,
        ):
            with self.assertRaisesRegex(InterruptedError, "original interruption"):
                run_browser(["browser"], cwd=Path(directory), env={}, receipt=Path(directory) / "budget.json")
            kill.assert_called_once_with(124, signal.SIGTERM)
            self.assertTrue(json.loads((Path(directory) / "budget.json").read_text())["interrupted"])


class DiagnosticSelection(unittest.TestCase):
    def test_only_one_explicit_740_bar_diagnostic_entry_is_admitted(self):
        from types import SimpleNamespace

        from scripts.backtest_diagnostic import validate_selection

        fields = dict(
            backtest_diagnostic=True,
            backtest_market_input=True,
            controlled_source_https=True,
            retained_market_input=True,
            contract_fuzz=False,
            restart_check=False,
            grep=None,
            tests=["e2e/backtest-diagnostics.spec.ts"],
        )
        validate_selection(SimpleNamespace(**fields))
        for change in [
            {"backtest_market_input": False},
            {"controlled_source_https": False},
            {"retained_market_input": False},
            {"contract_fuzz": True},
            {"restart_check": True},
            {"grep": "anything"},
            {"tests": ["e2e/backtest.spec.ts"]},
            {"tests": ["e2e/backtest-diagnostics.spec.ts", "e2e/backtest.spec.ts"]},
        ]:
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "BACKTEST_DIAGNOSTIC_SELECTION_INVALID"),
            ):
                validate_selection(SimpleNamespace(**(fields | change)))
        validate_selection(SimpleNamespace(backtest_diagnostic=False))


class DiagnosticCompletion(unittest.TestCase):
    def test_final_close_and_strict_stream_veto_browser_success(self):
        import json

        from scripts.backtest_diagnostic import finish_capture

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.jsonl"
            close = root / "close.jsonl"
            output = root / "completion.json"
            common = dict(schema_version=1, process_instance_id="original", pid=123)
            span = dict(common, trace_id="trace", span_id="span", module="backend", operation="test")
            rows = [
                dict(common, event_kind="session_start", mono_ns=0),
                dict(span, event_kind="operation_start", mono_ns=1),
                dict(
                    span,
                    event_kind="operation_end",
                    mono_ns=2,
                    start_mono_ns=1,
                    end_mono_ns=2,
                    duration_ns=1,
                    outcome="ok",
                ),
            ]
            events.write_text("".join(json.dumps(row) + "\n" for row in rows))
            receipt = dict(
                common, event_kind="session_end", mono_ns=3, shutdown_complete=True, dropped_events=0, io_errors=0
            )
            close.write_text(json.dumps(receipt) + "\n")
            self.assertEqual(finish_capture(events, close, 123, 0, output), 0)
            for change in (
                {"dropped_events": 1},
                {"io_errors": 1},
                {"shutdown_complete": False},
                {"pid": 124},
                {"process_instance_id": "other"},
                {"schema_version": 2},
                {"dropped_events": False},
                {"mono_ns": 0},
            ):
                close.write_text(json.dumps(receipt | change) + "\n")
                with self.subTest(change=change):
                    self.assertNotEqual(finish_capture(events, close, 123, 0, output), 0)
                    self.assertFalse(json.loads(output.read_text())["complete"])
            close.write_text(json.dumps(receipt) + "\n" + json.dumps(receipt) + "\n")
            self.assertNotEqual(finish_capture(events, close, 123, 0, output), 0)
            close.write_text(json.dumps(receipt) + "\n")
            for broken in (rows[:-1], rows + [rows[1]]):
                events.write_text("".join(json.dumps(row) + "\n" for row in broken))
                self.assertNotEqual(finish_capture(events, close, 123, 0, output), 0)
