from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from examples.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment
from examples.integration_demo.run_all import SCENARIOS
from onlyalpha.risk.enums import OnlyRiskReservationState


def complete_environment() -> OnlyIntegrationEnvironment:
    env = OnlyIntegrationEnvironment()
    for scenario in SCENARIOS:
        scenario(env)
    return env


def test_runtime_owns_managers_and_context_exposes_only_views() -> None:
    first = OnlyIntegrationEnvironment()
    second = OnlyIntegrationEnvironment()
    first.start()
    context = first.cluster.context
    assert context is not None
    forbidden = {
        "event_bus",
        "order_manager",
        "risk_service",
        "position_manager",
        "allocation_manager",
        "strategy_ledger_manager",
        "pipeline",
        "cache",
        "gateway",
    }
    assert forbidden.isdisjoint(dir(context))
    assert first.runtime.order_manager is not second.runtime.order_manager
    assert first.runtime.risk_service is not second.runtime.risk_service
    assert first.runtime.position_manager is not second.runtime.position_manager
    assert first.runtime.allocation_manager is not second.runtime.allocation_manager
    assert first.runtime.strategy_ledger_manager is not second.runtime.strategy_ledger_manager


def test_all_vertical_slice_snapshots_are_immutable() -> None:
    env = complete_environment()
    snapshot = env.final_snapshot()
    values = (
        *snapshot.order_snapshots,
        *env.runtime.position_manager.closed(),
        *env.runtime.allocation_manager.closed(),
        *snapshot.ledger_snapshots,
        *env.cluster.snapshots,
    )
    assert values
    for value in values:
        params = getattr(type(value), "__dataclass_params__", None)
        assert params is not None and params.frozen
    with pytest.raises(FrozenInstanceError):
        snapshot.order_snapshots[0].version = 999  # type: ignore[misc]


def test_all_reservation_lifecycles_close_after_full_fills() -> None:
    env = complete_environment()
    risk = env.runtime.risk_service.reservations.snapshot_all()
    assert risk and all(item.state is OnlyRiskReservationState.CONSUMED for item in risk)
    ledger = env.runtime.strategy_ledger_manager.list_ledgers()[0]
    assert ledger.reservations and all(item.remaining_amount.amount == 0 for item in ledger.reservations)
    assert env.sell_order is not None and env.sell_order.order_id is not None
    position = env.runtime.position_reservation_manager.get(env.sell_order.order_id)
    assert position is not None and position.remaining_quantity.value == 0
    position_facts = tuple(item.event_type for item in env.event_recorder.events if item.source == "position_manager")
    assert position_facts == ("POSITION_OPENED", "POSITION_SETTLED", "POSITION_CLOSED")


def test_runtime_pipeline_snapshot_precedes_cluster_callback() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    env.process_bar(DAY_ONE, 0, "10.00")
    callback_snapshot = env.cluster.snapshots[-1]
    pipeline_snapshot = env.market_updates[-1].snapshot
    context = env.cluster.context
    assert context is not None
    assert callback_snapshot.ts_event == pipeline_snapshot.ts_event
    assert callback_snapshot.updated_bar_types == pipeline_snapshot.updated_bar_types
    assert callback_snapshot.cluster_id == context.cluster_id


def test_production_import_graph_has_no_cycles() -> None:
    root = Path("src/onlyalpha")
    graph: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        module = ".".join(path.with_suffix("").parts[1:])
        graph[module] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("onlyalpha"):
                graph[module].add(node.module)
            elif isinstance(node, ast.Import):
                graph[module].update(alias.name for alias in node.names if alias.name.startswith("onlyalpha"))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            raise AssertionError(f"circular dependency detected at {module}")
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            if dependency in graph:
                visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)


def test_event_bus_does_not_drive_production_state_machines() -> None:
    subscribers: list[str] = []
    for path in Path("src/onlyalpha").rglob("*.py"):
        if path == Path("src/onlyalpha/event/bus.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "subscribe"
            for node in ast.walk(tree)
        ):
            subscribers.append(str(path))
    assert subscribers == []


def test_integration_demo_does_not_modify_manager_internals() -> None:
    forbidden_attributes = {"_active", "_state", "_ledgers", "_reservations", "_by_order"}
    offenders: list[str] = []
    for path in Path("examples/integration_demo").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                offenders.append(f"{path}:{node.lineno}:{node.attr}")
    assert offenders == []
