from __future__ import annotations

from pathlib import Path

import pytest

SCOPE_MARKERS = frozenset({"contract", "architecture", "integration", "scenario"})
CONCERN_MARKERS = frozenset({"recovery", "sim_recovery", "conformance", "external", "exhaustive", "miniqmt"})
EXTERNAL_REQUIREMENT_MARKERS = frozenset({"requires_network", "requires_tushare", "requires_broker_account"})


def path_scope(path: Path) -> str | None:
    value = path.as_posix().lower()
    if "/architecture/" in f"/{value}":
        return "architecture"
    if "/scenario/" in f"/{value}":
        return "scenario"
    if "/integration/" in f"/{value}":
        return "integration"
    if "/packages/" in f"/{value}":
        return "contract"
    return None


def path_concerns(path: Path) -> frozenset[str]:
    value = path.as_posix().lower()
    name = path.name.lower()
    concerns: set[str] = set()
    if any(
        token in value if token == "recovery" else token in name
        for token in ("recovery", "checkpoint", "restart", "outbox")
    ):
        concerns.add("recovery")
    if "/conformance/" in f"/{value}":
        concerns.add("conformance")
    return frozenset(concerns)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    errors: list[str] = []
    for item in items:
        path = Path(str(item.path))
        existing = {marker.name for marker in item.iter_markers()}
        scopes = existing & SCOPE_MARKERS
        if not scopes:
            scope = path_scope(path)
            if scope is not None:
                item.add_marker(getattr(pytest.mark, scope))
        elif len(scopes) > 1:
            errors.append(f"{item.nodeid}: expected at most one scope marker, found {sorted(scopes)}")
        for concern in path_concerns(path) - existing:
            item.add_marker(getattr(pytest.mark, concern))
        markers = {marker.name for marker in item.iter_markers()}
        if markers & EXTERNAL_REQUIREMENT_MARKERS:
            item.add_marker(pytest.mark.external)
            markers.add("external")
        if "external" in markers and not markers & EXTERNAL_REQUIREMENT_MARKERS:
            errors.append(f"{item.nodeid}: external test lacks an explicit requirement marker")
    if errors:
        raise pytest.UsageError("illegal test markers:\n" + "\n".join(errors))
