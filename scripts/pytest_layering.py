from __future__ import annotations

from pathlib import Path

import pytest

PRIMARY_MARKERS = frozenset(
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
    }
)


def path_marker(path: Path) -> str:
    value = path.as_posix().lower()
    name = path.name.lower()
    if "/architecture/" in f"/{value}":
        return "architecture"
    if "recovery" in value or "checkpoint" in name or "restart" in name or "outbox" in name:
        return "recovery"
    if "/scenario/" in f"/{value}":
        return "scenario"
    if "conformance" in value:
        return "conformance"
    if "/integration/" in f"/{value}":
        return "integration"
    if "/packages/" in f"/{value}":
        return "contract"
    return "unit"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    errors: list[str] = []
    for item in items:
        path = Path(str(item.path))
        existing = {marker.name for marker in item.iter_markers()}
        if not existing & PRIMARY_MARKERS:
            item.add_marker(getattr(pytest.mark, path_marker(path)))
        value = path.as_posix().lower()
        if "onlyalpha-plugin-miniqmt" in value:
            item.add_marker(pytest.mark.miniqmt)
        markers = {marker.name for marker in item.iter_markers()}
        if markers & {"requires_network", "requires_tushare", "requires_local_qmt", "requires_broker_account"}:
            item.add_marker(pytest.mark.external)
            markers.add("external")
        if "requires_local_qmt" in markers:
            item.add_marker(pytest.mark.windows)
        if "external" in markers and not markers & {
            "requires_network",
            "requires_tushare",
            "requires_local_qmt",
            "requires_broker_account",
        }:
            errors.append(f"{item.nodeid}: external test lacks an explicit requirement marker")
        if "requires_broker_account" in markers and not {"requires_local_qmt", "windows"} <= markers:
            errors.append(f"{item.nodeid}: broker-account test must also require local QMT and Windows")
    if errors:
        raise pytest.UsageError("illegal test markers:\n" + "\n".join(errors))
