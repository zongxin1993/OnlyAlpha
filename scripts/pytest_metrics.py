from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

_started = 0.0
_reports: list[dict[str, Any]] = []
_markers: Counter[str] = Counter()
_paths: Counter[str] = Counter()
_worker_payloads: list[dict[str, Any]] = []
_item_markers: dict[str, tuple[str, ...]] = {}
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
    global _started
    _started = time.perf_counter()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        names = tuple(sorted({marker.name for marker in item.iter_markers()}))
        _item_markers[item.nodeid] = names
        _markers.update(names)
        parts = Path(str(item.path)).parts
        _paths["/".join(parts[:2]) if len(parts) > 1 else str(item.path)] += 1


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
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
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
        ).stdout.strip()
    except OSError:
        commit = "unknown"
    payload = {
        "commit": commit or "unknown",
        "lane": lane,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
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
        "slowest_tests": sorted(_reports, key=lambda item: item["seconds"], reverse=True)[:20],
        "marker_counts": dict(sorted(_markers.items())),
        "path_counts": dict(sorted(_paths.items())),
        "exit_code": exitstatus,
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
