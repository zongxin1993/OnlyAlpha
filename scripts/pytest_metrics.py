from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import time
from collections import Counter
from os import PathLike
from pathlib import Path
from typing import Any

import pytest

_started = 0.0
_reports: list[dict[str, Any]] = []
_markers: Counter[str] = Counter()
_paths: Counter[str] = Counter()
_worker_payloads: list[dict[str, Any]] = []
_item_markers: dict[str, tuple[str, ...]] = {}
_phase_seconds: Counter[str] = Counter()
_counters: Counter[str] = Counter()
_instrumented = False
_KNOWN_MARKERS = frozenset(
    {
        "unit",
        "contract",
        "architecture",
        "integration",
        "scenario",
        "conformance",
        "recovery",
        "external",
        "performance",
        "exhaustive",
        "slow",
        "miniqmt",
        "requires_network",
        "requires_tushare",
        "requires_local_qmt",
        "requires_broker_account",
        "windows",
    }
)


def pytest_configure(config: pytest.Config) -> None:
    global _started, _instrumented
    _started = time.perf_counter()
    if _instrumented:
        return
    _instrumented = True
    _instrument_test_costs()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        names = tuple(sorted({marker.name for marker in item.iter_markers()}))
        _item_markers[item.nodeid] = names
        _markers.update(names)
        parts = Path(str(item.path)).parts
        _paths["/".join(parts[:2]) if len(parts) > 1 else str(item.path)] += 1


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _phase_seconds[report.when] += report.duration
    if report.when == "call" or (report.when == "setup" and report.skipped):
        path = report.nodeid.split("::", maxsplit=1)[0]
        _reports.append(
            {
                "nodeid": report.nodeid,
                "seconds": report.duration,
                "outcome": report.outcome,
                "markers": tuple(sorted(set(report.keywords) & _KNOWN_MARKERS)) or _item_markers.get(report.nodeid, ()),
                "path": path,
            }
        )


def pytest_testnodedown(node: Any, error: object | None) -> None:
    payload = node.workeroutput.get("onlyalpha_metrics")
    if payload:
        _worker_payloads.append(payload)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if hasattr(session.config, "workerinput"):
        session.config.workeroutput["onlyalpha_metrics"] = {  # type: ignore[attr-defined]
            "reports": _reports,
            "markers": dict(_markers),
            "paths": dict(_paths),
            "phase_seconds": dict(_phase_seconds),
            "counters": dict(_counters),
        }
        return
    if _reports:
        _markers.clear()
        _paths.clear()
        for report in _reports:
            _markers.update(report.get("markers", ()))
            parts = Path(report.get("path", report["nodeid"])).parts
            _paths["/".join(parts[:2]) if len(parts) > 1 else report["path"]] += 1
    lane = os.environ.get("ONLYALPHA_TEST_LANE")
    output = os.environ.get("ONLYALPHA_TEST_METRICS")
    if not lane or not output:
        return
    outcomes = Counter(report["outcome"] for report in _reports)
    phases = Counter() if _worker_payloads else Counter(_phase_seconds)
    counters = Counter(_counters)
    for worker in _worker_payloads:
        phases.update(worker.get("phase_seconds", {}))
        counters.update(worker.get("counters", {}))
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
        ).stdout.strip()
    except OSError:
        commit = "unknown"
    payload = {
        "commit": commit or "unknown",
        "git_branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "baseline_commit": os.environ.get("ONLYALPHA_TEST_BASELINE_COMMIT", "unknown"),
        "lane": lane,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "machine_id": hashlib.sha256(f"{platform.node()}|{platform.platform()}|{os.cpu_count()}".encode()).hexdigest()[
            :16
        ],
        "worker_count": (
            os.cpu_count() or 0
            if os.environ.get("ONLYALPHA_TEST_WORKERS", "0") == "auto"
            else int(os.environ.get("ONLYALPHA_TEST_WORKERS", "0"))
        ),
        "distribution_mode": os.environ.get("ONLYALPHA_TEST_DIST", "no"),
        "collected": session.testscollected,
        "passed": outcomes["passed"],
        "failed": outcomes["failed"],
        "skipped": outcomes["skipped"],
        "total_seconds": round(time.perf_counter() - _started, 6),
        "setup_seconds": round(phases["setup"], 6),
        "call_seconds": round(phases["call"], 6),
        "teardown_seconds": round(phases["teardown"], 6),
        "cache_hit_count": counters["cache_hit_count"],
        "engine_run_count": counters["engine_run_count"],
        "sqlite_database_count": counters["sqlite_database_count"],
        "parquet_write_count": counters["parquet_write_count"],
        "slowest_tests": sorted(_reports, key=lambda item: item["seconds"], reverse=True)[:20],
        "marker_counts": dict(sorted(_markers.items())),
        "path_counts": dict(sorted(_paths.items())),
        "exhaustive_test_count": _markers["exhaustive"],
        "recovery_test_count": _markers["recovery"],
        "conformance_test_count": _markers["conformance"],
        "exit_code": exitstatus,
        "tests": {
            report["nodeid"]: round(report["seconds"], 6)
            for report in sorted(_reports, key=lambda item: item["nodeid"])
        },
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    thresholds = {"unit": 1.0, "integration": 10.0, "recovery": 30.0}
    for report in _reports:
        for marker, threshold in thresholds.items():
            if marker in report.get("markers", ()) and report["seconds"] > threshold:
                print(
                    f"PERFORMANCE WARNING: {marker} test {report['nodeid']} took {report['seconds']:.2f}s "
                    f"(budget {threshold:.0f}s)"
                )
                break


def record_metric_counter(name: str, increment: int = 1) -> None:
    if increment < 0:
        raise ValueError("metric counter increment cannot be negative")
    _counters[name] += increment


def _git_value(*args: str) -> str:
    try:
        value = subprocess.run(["git", *args], capture_output=True, check=False, text=True).stdout.strip()
    except OSError:
        return "unknown"
    return value or "unknown"


def _instrument_test_costs() -> None:
    from onlyalpha.engine.engine import OnlyEngine

    original_run = OnlyEngine.run

    def counted_engine_run(self: OnlyEngine):  # type: ignore[no-untyped-def]
        record_metric_counter("engine_run_count")
        return original_run(self)

    OnlyEngine.run = counted_engine_run  # type: ignore[method-assign]

    original_connect = sqlite3.connect

    def counted_connect(database: str | bytes | PathLike[str] | PathLike[bytes], *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        path = _created_sqlite_path(database, kwargs)
        if path is not None and not path.exists():
            record_metric_counter("sqlite_database_count")
        return original_connect(database, *args, **kwargs)  # type: ignore[arg-type]

    sqlite3.connect = counted_connect  # type: ignore[assignment]

    try:
        import pyarrow.parquet as parquet
    except ImportError:
        return
    original_write_table = parquet.write_table

    def counted_write_table(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        record_metric_counter("parquet_write_count")
        return original_write_table(*args, **kwargs)

    parquet.write_table = counted_write_table


def _created_sqlite_path(
    database: str | bytes | PathLike[str] | PathLike[bytes], kwargs: dict[str, object]
) -> Path | None:
    raw = os.fsdecode(database)
    if raw == ":memory:" or raw.startswith("file::memory:"):
        return None
    if raw.startswith("file:") and bool(kwargs.get("uri")):
        location, _, query = raw[5:].partition("?")
        parameters = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
        if parameters.get("mode") in {"ro", "rw", "memory"}:
            return None
        return Path(location)
    return Path(raw)
