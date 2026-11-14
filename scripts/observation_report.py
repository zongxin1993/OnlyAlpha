"""版本化诊断事件的离线时间归因，不产生正式回测事实。"""

import json
from collections import Counter
from statistics import median

FIELDS = frozenset(
    """schema_version event_kind process_instance_id pid trace_id span_id
parent_span_id links request_id command_id run_id attempt module operation outcome
mono_ns start_mono_ns end_mono_ns duration_ns wall_time_unix_ns work_items bytes
error_code lock_type device inode errno dropped_events io_errors shutdown_complete
file_path expected_value actual_value""".split()
)
KINDS = {
    "operation_start",
    "operation_end",
    "operation_abandoned",
    "session_start",
    "session_end",
    "diagnostic_loss",
    "lock_wait",
    "lock_acquired",
    "lock_released",
    "lock_contention",
    "summary",
    "lock_release_begin",
    "lock_error",
}


def lock_associations(rows):
    """保守的同进程锁关联。只读事件表，不控制锁，不认证所有 OS 持有者不存在。

    OS 成功后 acquire marker 到 close 前 marker 是可证明的持有区间；end 是关闭后的上界。
    必须严格覆盖原 wait→attempt_end，避免释放/重获之间的窗口被猜成持有关系。
    """
    groups, receipts, processes = {}, {}, set()
    for row in rows:
        process = row["process_instance_id"]
        processes.add(process)
        if row["event_kind"] == "session_end":
            receipts.setdefault(process, []).append(row)
        if row.get("span_id") is not None:
            groups.setdefault((process, row["span_id"]), {}).setdefault(row["event_kind"], []).append(row)
    tainted = {
        process
        for process in processes
        if len(receipts.get(process, [])) != 1
        or any(
            not r.get("shutdown_complete") or r.get("dropped_events", 0) or r.get("io_errors", 0)
            for r in receipts.get(process, [])
        )
    }
    tainted.update(r["process_instance_id"] for r in rows if r["event_kind"] == "diagnostic_loss")

    def one(group, kind):
        values = group.get(kind, [])
        return values[0] if len(values) == 1 else None

    def consistent(events):
        if any(r is None for r in events):
            return False
        first = events[0]
        if not all(field in first for field in ("device", "inode", "lock_type")):
            return False
        return all(
            all(
                r.get(field) == first.get(field)
                for field in (
                    "device",
                    "inode",
                    "lock_type",
                    "trace_id",
                    "pid",
                    "run_id",
                    "command_id",
                    "request_id",
                    "links",
                )
            )
            for r in events[1:]
        )

    result = []
    for (process, span), group in groups.items():
        failure = one(group, "lock_contention")
        if failure is None:
            continue
        record = {
            "process_instance_id": process,
            "span_id": span,
            "command_id": failure.get("command_id"),
            "request_id": failure.get("request_id"),
            "errno": failure.get("errno"),
            "device": failure.get("device"),
            "inode": failure.get("inode"),
            "status": "unknown",
            "holders": [],
            "external_holders": "unknown",
        }
        wait, ended = one(group, "lock_wait"), one(group, "operation_end")
        if process in tainted:
            record["reason"] = "diagnostic_loss_or_missing_close"
        elif (
            not failure.get("command_id")
            or not consistent([wait, failure, ended])
            or ended.get("outcome") != "contended"
            or not (wait["mono_ns"] <= failure["mono_ns"] <= ended["mono_ns"])
        ):
            record["reason"] = "incomplete_attempt_identity_or_interval"
        else:
            for (holder_process, holder_span), holder in groups.items():
                if holder_process != process or "lock_acquired" not in holder:
                    continue
                acquired, before_close, released, end = [
                    one(holder, kind)
                    for kind in ("lock_acquired", "lock_release_begin", "lock_released", "operation_end")
                ]
                if (
                    not consistent([acquired, before_close, released, end])
                    or not (acquired.get("run_id") or acquired.get("command_id"))
                    or end.get("outcome") != "released"
                ):
                    continue
                if (acquired["device"], acquired["inode"]) != (wait["device"], wait["inode"]):
                    continue
                compatible = (
                    wait["lock_type"] == "exclusive" and acquired["lock_type"] in {"shared", "exclusive"}
                ) or (wait["lock_type"] == "shared" and acquired["lock_type"] == "exclusive")
                if (
                    compatible
                    and acquired["mono_ns"]
                    < wait["mono_ns"]
                    <= ended["mono_ns"]
                    < before_close["mono_ns"]
                    <= released["mono_ns"]
                    <= end["mono_ns"]
                ):
                    record["holders"].append(
                        {
                            "process_instance_id": process,
                            "span_id": holder_span,
                            "trace_id": acquired["trace_id"],
                            "run_id": acquired.get("run_id"),
                            "command_id": acquired.get("command_id"),
                            "lock_type": acquired["lock_type"],
                            "guaranteed_hold_start_ns": acquired["mono_ns"],
                            "guaranteed_hold_end_ns": before_close["mono_ns"],
                        }
                    )
            record["status"] = "known_local_holders" if record["holders"] else "unknown"
            record["reason"] = (
                "exact_object_and_guaranteed_interval" if record["holders"] else "no_proven_compatible_local_holder"
            )
        result.append(record)
    return result


def _union(intervals):
    end = total = 0
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def observation_report(rows, *, require_session_end=False):
    """仅同一 process_instance 的直接子操作参与区间并集；锁持有是独立资源跨度。

    缺证向祖先传播。丢失/未正常关闭影响该进程所有操作，不能推断丢失的子调用不存在。
    uncovered 仅表示未被直接子阶段覆盖的 wall time，绝非 CPU 或算法独占成本。
    """
    rows = list(rows)
    resource_keys = {
        (r.get("process_instance_id"), r.get("span_id")) for r in rows if r.get("event_kind") == "lock_acquired"
    }
    spans, ends, incomplete, processes, closed, lossy = {}, {}, set(), set(), set(), set()
    for row in rows:
        if type(row.get("schema_version")) is not int or row["schema_version"] != 1 or set(row) - FIELDS:
            raise ValueError("unsupported observation schema or non-whitelisted field")
        if type(row.get("pid")) is not int or row["pid"] <= 0:
            raise ValueError("invalid process identity")
        for field in (
            "mono_ns",
            "start_mono_ns",
            "end_mono_ns",
            "duration_ns",
            "wall_time_unix_ns",
            "work_items",
            "bytes",
            "attempt",
            "dropped_events",
            "io_errors",
            "device",
            "inode",
            "errno",
        ):
            if field in row and (type(row[field]) is not int or row[field] < 0):
                raise ValueError("invalid observation counter")
        for field in (
            "trace_id",
            "span_id",
            "parent_span_id",
            "links",
            "request_id",
            "command_id",
            "run_id",
            "module",
            "operation",
            "outcome",
            "error_code",
            "lock_type",
            "file_path",
            "expected_value",
            "actual_value",
        ):
            if row.get(field) is not None and not isinstance(row[field], str):
                raise ValueError("invalid observation association")
        if "shutdown_complete" in row and type(row["shutdown_complete"]) is not bool:
            raise ValueError("invalid shutdown receipt")
        kind, process = row.get("event_kind"), row.get("process_instance_id")
        if row.get("operation") == "evidence.witness.failure":
            if kind != "summary" or row.get("outcome") != "failed":
                raise ValueError("invalid Witness diagnostic event")
            for field, limit in (
                ("file_path", 4096),
                ("expected_value", 256),
                ("actual_value", 256),
                ("error_code", 256),
            ):
                if not isinstance(row.get(field), str) or not row[field] or len(row[field].encode("utf-8")) > limit:
                    raise ValueError("incomplete Witness diagnostic details")
        if kind not in KINDS or not isinstance(process, str) or not process:
            raise ValueError("invalid event identity")
        at = row.get("mono_ns")
        if isinstance(at, bool) or not isinstance(at, int) or at < 0:
            raise ValueError("invalid monotonic timestamp")
        processes.add(process)
        key = (process, row.get("span_id"))
        if kind in {"operation_start", "operation_end", "operation_abandoned"}:
            if not all(row.get(f) for f in ("span_id", "trace_id", "module", "operation")):
                raise ValueError("missing operation identity")
        if kind == "operation_start":
            if key in spans:
                raise ValueError("duplicate operation start")
            spans[key] = dict(row)
        elif kind in {"operation_end", "operation_abandoned"}:
            if key in ends:
                raise ValueError("duplicate operation end")
            ends[key] = row
        elif kind == "session_end":
            if process in closed:
                raise ValueError("duplicate session end")
            closed.add(process)
            if not row.get("shutdown_complete") or row.get("dropped_events", 0) or row.get("io_errors", 0):
                lossy.add(process)
        elif kind == "diagnostic_loss":
            lossy.add(process)
    if require_session_end:
        for process in processes - closed:
            lossy.add(process)
            incomplete.add(f"missing_session_end:{process}")
    incomplete.update(f"diagnostic_loss:{p}" for p in lossy)
    invalid = set()
    for key, row in spans.items():
        end = ends.get(key)
        if end is None or end["event_kind"] == "operation_abandoned":
            invalid.add(key)
            incomplete.add(f"missing_end:{key}")
            continue
        for field in (
            "trace_id",
            "parent_span_id",
            "module",
            "operation",
            "pid",
            "run_id",
            "command_id",
            "request_id",
            "attempt",
            "links",
        ):
            if row.get(field) != end.get(field):
                raise ValueError("operation end identity mismatch")
        start_ns, end_ns = row["mono_ns"], end["mono_ns"]
        if (
            end_ns < start_ns
            or end.get("start_mono_ns") != start_ns
            or end.get("end_mono_ns") != end_ns
            or end.get("duration_ns") != end_ns - start_ns
        ):
            raise ValueError("invalid operation interval")
        row.update(end)
        row["start_mono_ns"] = start_ns
    for key in ends.keys() - spans.keys():
        invalid.add(key)
        incomplete.add(f"missing_start:{key}")
        parent = ends[key].get("parent_span_id")
        if parent:
            invalid.add((key[0], parent))
    for key, row in spans.items():
        parent_key = (key[0], row.get("parent_span_id"))
        if row.get("parent_span_id") is not None:
            parent = spans.get(parent_key)
            if parent is None or parent.get("trace_id") != row["trace_id"]:
                invalid.add(key)
                incomplete.add(f"missing_parent:{key}")
        seen, cursor = {key}, parent_key
        while cursor in spans:
            if cursor in seen:
                raise ValueError("cyclic operation parent")
            seen.add(cursor)
            cursor = (cursor[0], spans[cursor].get("parent_span_id"))
    # 子阶段缺证向全部祖先传播；同一进程丢失会使所有未覆盖时间未知。
    for key, row in spans.items():
        parent_key = (key[0], row.get("parent_span_id"))
        parent = spans.get(parent_key)
        if (
            parent
            and "end_mono_ns" in row
            and "end_mono_ns" in parent
            and (row["start_mono_ns"] < parent["start_mono_ns"] or row["end_mono_ns"] > parent["end_mono_ns"])
        ):
            invalid.add(parent_key)
            incomplete.add(f"child_outside_parent:{key}")
    invalid.update(key for key in spans if key[0] in lossy)
    for key in list(invalid):
        cursor = key
        while cursor in spans:
            cursor = (cursor[0], spans[cursor].get("parent_span_id"))
            invalid.add(cursor)
    children = {}
    for child_key, child in spans.items():
        children.setdefault((child_key[0], child.get("parent_span_id")), []).append(child_key)
    for key, row in spans.items():
        row["resource_interval"] = key in resource_keys or row["operation"].endswith(".hold")
    for key, row in spans.items():
        row["uncovered_ns"] = row["child_union_ns"] = None
        row["complete"] = key not in invalid and "end_mono_ns" in row
        if not row["complete"]:
            continue
        intervals = []
        for child_key in children.get(key, []):
            child = spans[child_key]
            if child.get("resource_interval"):
                continue
            start, end = child["start_mono_ns"], child["end_mono_ns"]
            if start < row["start_mono_ns"] or end > row["end_mono_ns"]:
                incomplete.add(f"child_outside_parent:{child_key}")
                row["complete"] = False
            intervals.append((max(start, row["start_mono_ns"]), min(end, row["end_mono_ns"])))
        if row["complete"]:
            row["child_union_ns"] = _union(intervals)
            row["uncovered_ns"] = row["duration_ns"] - row["child_union_ns"]
    return {
        "schema_version": 1,
        "operations": list(spans.values()),
        "complete": not incomplete and all(r["complete"] for r in spans.values()),
        "incomplete": sorted(incomplete),
        "locks": lock_associations(rows),
        "summaries": [row for row in rows if row["event_kind"] == "summary"],
    }


def legacy_observation_report(lines):
    """历史线程栈没有进程实例/单调区间，保留原始耗时，不提升为 v1 因果证据。"""
    pending, operations = {}, []
    incomplete = {"legacy_missing_process_instance_and_monotonic_intervals"}
    for line in lines:
        if not line.startswith("BACKTEST_PROFILE "):
            continue
        row = json.loads(line.partition(" ")[2])
        key = (row.get("pid"), row.get("id"))
        if row.get("event") == "begin":
            if key in pending:
                incomplete.add("legacy_ambiguous_identity")
            pending[key] = row
        elif row.get("event") == "end":
            start = pending.pop(key, None)
            if start is None:
                incomplete.add("legacy_missing_start")
                continue
            duration = int(row["elapsed_ns"])
            if duration < 0:
                raise ValueError("invalid legacy duration")
            operations.append(
                {
                    "process_instance_id": None,
                    "legacy_pid": key[0],
                    "legacy_id": key[1],
                    "run_id": start.get("run"),
                    "operation": start.get("stage"),
                    "duration_ns": duration,
                    "outcome": "ok" if row.get("ok") else "failed",
                    "uncovered_ns": None,
                    "parent_span_id": None,
                    "complete": False,
                }
            )
    if pending:
        incomplete.add("legacy_missing_end")
    return {
        "schema_version": 1,
        "source": "legacy_BACKTEST_PROFILE",
        "complete": False,
        "operations": operations,
        "incomplete": sorted(incomplete),
    }


def load_observation_files(paths):
    rows, errors = [], []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            if line.startswith("ONLYALPHA_DIAGNOSTIC "):
                line = line.partition(" ")[2]
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not an event object")
            except ValueError:
                # 不把损坏行内容复制到报告，尤其不能把原始日志当作异常详情输出。
                errors.append({"path": str(path), "line": number, "code": "DIAGNOSTIC_JSON_INVALID"})
                continue
            rows.append(row)
    report = observation_report(rows, require_session_end=True)
    report["read_errors"] = errors
    if errors or not report["operations"]:
        report["complete"] = False
        report["incomplete"].append("stream_parse_loss" if errors else "no_operations")
        for row in report["operations"]:
            row.update(complete=False, uncovered_ns=None, child_union_ns=None)
        for row in report["locks"]:
            row.update(status="unknown", holders=[], reason="stream_parse_loss")
    return report


def flow_summary(report, run_id):
    """按原 Run 汇总已观察调用；包含成本可以重叠，不能相加冒充流程延迟。"""
    operations = [row for row in report["operations"] if row.get("run_id") == run_id]
    groups = {}
    for row in operations:
        groups.setdefault((row["module"], row["operation"], row.get("resource_interval", False)), []).append(row)
    hotspots = []
    for (module, operation, resource), rows in groups.items():
        closed = [row for row in rows if "duration_ns" in row]
        durations = [row["duration_ns"] for row in closed]
        complete = [row for row in rows if row["complete"]]
        hotspots.append(
            dict(
                module=module,
                operation=operation,
                resource_interval=resource,
                observed_calls=len(rows),
                closed_durations_observed=len(closed),
                coverage_complete_calls=len(complete),
                inclusive_call_duration_sum_ns=sum(durations) if durations else None,
                median_observed_ns=median(durations) if durations else None,
                min_observed_ns=min(durations) if durations else None,
                max_observed_ns=max(durations) if durations else None,
                uncovered_sum_ns=sum(row["uncovered_ns"] for row in complete) if len(complete) == len(rows) else None,
                work_items_observed=sum(row.get("work_items", 0) for row in closed),
                bytes_observed=sum(row.get("bytes", 0) for row in closed),
                outcomes=dict(Counter(row.get("outcome", "incomplete") for row in rows)),
            )
        )
    hotspots.sort(key=lambda row: -(row["inclusive_call_duration_sum_ns"] or 0))
    fields = (
        "process_instance_id",
        "trace_id",
        "span_id",
        "module",
        "operation",
        "start_mono_ns",
        "end_mono_ns",
        "duration_ns",
        "child_union_ns",
        "uncovered_ns",
        "complete",
        "resource_interval",
    )
    roots = [
        {**{key: row.get(key) for key in fields}, "start_mono_ns": row.get("start_mono_ns", row["mono_ns"])}
        for row in operations
        if row.get("parent_span_id") is None
    ]
    roots.sort(key=lambda row: (row["process_instance_id"], row["start_mono_ns"]))
    return dict(
        schema_version=1,
        run_id=run_id,
        complete=report["complete"] and bool(operations),
        counts_are_complete=report["complete"] and bool(operations),
        inclusive_call_totals_are_flow_latency=False,
        roots=roots,
        hotspots=hotspots,
        critical_path={
            "status": "dependency_not_proven",
            "reason": "parent/child wall coverage alone does not prove await dependencies; use the stage tree and original call sites",
        },
        tree_index="operations: process_instance_id/span_id -> parent_span_id; resource roots use links",
    )
