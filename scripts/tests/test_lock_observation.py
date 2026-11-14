"""只按原锁对象与已证明的持有区间关联；不把时间相邻当作持锁关系。"""

import unittest

from scripts.observation_report import lock_associations


def row(kind, span, at, **extra):
    return dict(
        schema_version=1,
        event_kind=kind,
        process_instance_id="p",
        pid=10,
        trace_id=span,
        span_id=span,
        module="runtime",
        operation="generation.hold" if span == "hold" else "generation.lock_attempt",
        mono_ns=at,
        device=1,
        inode=2,
        lock_type="shared" if span == "hold" else "exclusive",
        **extra,
    )


def fixture():
    return [
        row("operation_start", "hold", 9, run_id="run"),
        row("lock_acquired", "hold", 10, run_id="run"),
        row("operation_start", "try", 19, command_id="candidate"),
        row("lock_wait", "try", 20, command_id="candidate"),
        row("lock_contention", "try", 25, command_id="candidate", errno=11),
        row(
            "operation_end",
            "try",
            30,
            command_id="candidate",
            outcome="contended",
            start_mono_ns=19,
            end_mono_ns=30,
            duration_ns=11,
        ),
        row("lock_release_begin", "hold", 80, run_id="run"),
        row("lock_released", "hold", 90, run_id="run"),
        row(
            "operation_end",
            "hold",
            91,
            run_id="run",
            outcome="released",
            start_mono_ns=9,
            end_mono_ns=91,
            duration_ns=82,
        ),
        dict(
            schema_version=1,
            event_kind="session_end",
            process_instance_id="p",
            pid=10,
            mono_ns=100,
            shutdown_complete=True,
            dropped_events=0,
            io_errors=0,
        ),
    ]


class LockObservationTests(unittest.TestCase):
    def test_original_object_and_guaranteed_hold_cover_whole_failed_attempt(self):
        result = lock_associations(fixture())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "known_local_holders")
        self.assertEqual(result[0]["holders"][0]["run_id"], "run")
        self.assertEqual(result[0]["command_id"], "candidate")
        self.assertEqual(result[0]["errno"], 11)

    def test_missing_contender_or_holder_ownership_is_unknown(self):
        for span, fields in [("try", ("command_id",)), ("hold", ("run_id", "command_id"))]:
            rows = fixture()
            for row in rows:
                if row.get("span_id") == span:
                    for field in fields:
                        row.pop(field, None)
            with self.subTest(span=span):
                result = lock_associations(rows)[0]
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["holders"], [])

    def test_preparation_holder_can_be_owned_by_command_without_a_run(self):
        rows = fixture()
        for row in rows:
            if row.get("span_id") == "hold":
                row.pop("run_id", None)
                row["command_id"] = "holder-preparation"
        self.assertEqual(lock_associations(rows)[0]["status"], "known_local_holders")

    def test_wrong_inode_other_process_missing_preclose_or_loss_are_unknown(self):
        for kind in ["inode", "process", "missing_preclose", "loss", "edge_race", "compatible_shared"]:
            rows = fixture()
            if kind == "inode":
                for r in rows:
                    if r.get("span_id") == "hold":
                        r["inode"] = 3
            elif kind == "process":
                for r in rows:
                    if r.get("span_id") == "hold":
                        r["process_instance_id"] = "restarted"
                rows.append(dict(rows[-1], process_instance_id="restarted"))
            elif kind == "missing_preclose":
                rows = [r for r in rows if r["event_kind"] != "lock_release_begin"]
            elif kind == "loss":
                rows[-1]["dropped_events"] = 1
            elif kind == "edge_race":
                for r in rows:
                    if r["event_kind"] == "lock_release_begin":
                        r["mono_ns"] = 29
            else:
                for r in rows:
                    if r.get("span_id") == "try":
                        r["lock_type"] = "shared"
            with self.subTest(kind=kind):
                result = lock_associations(rows)[0]
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["holders"], [])


if __name__ == "__main__":
    unittest.main()
