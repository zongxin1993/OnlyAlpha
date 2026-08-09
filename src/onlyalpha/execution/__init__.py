"""Broker-driven execution API with cycle-safe lazy compatibility exports."""

from __future__ import annotations

from importlib import import_module

_EXPORT_MODULES = (
    "onlyalpha.execution.accepted_fact",
    "onlyalpha.execution.accepted_identity",
    "onlyalpha.execution.accepted_planner",
    "onlyalpha.execution.authority_state",
    "onlyalpha.execution.capability",
    "onlyalpha.execution.causal_recovery",
    "onlyalpha.execution.close_cost_authority",
    "onlyalpha.execution.committed",
    "onlyalpha.execution.economic_invariants",
    "onlyalpha.execution.enums",
    "onlyalpha.execution.event_buffer",
    "onlyalpha.execution.execution_state",
    "onlyalpha.execution.fill_identity",
    "onlyalpha.execution.invariants",
    "onlyalpha.execution.lifecycle_reducers",
    "onlyalpha.execution.market_evidence",
    "onlyalpha.execution.models",
    "onlyalpha.execution.planned_trade",
    "onlyalpha.execution.planning_context",
    "onlyalpha.execution.planning_results",
    "onlyalpha.execution.processor",
    "onlyalpha.execution.projection_targets",
    "onlyalpha.execution.reservation_presence",
    "onlyalpha.execution.scope",
    "onlyalpha.execution.state",
    "onlyalpha.execution.support",
    "onlyalpha.execution.terminal_fact",
    "onlyalpha.execution.terminal_identity",
    "onlyalpha.execution.terminal_planner",
    "onlyalpha.execution.trade_planner",
    "onlyalpha.transaction.applied_projection",
    "onlyalpha.transaction.codec",
    "onlyalpha.transaction.coordinator",
    "onlyalpha.transaction.delivery",
    "onlyalpha.transaction.event_identity",
    "onlyalpha.transaction.identity",
    "onlyalpha.transaction.persistence_ports",
    "onlyalpha.transaction.projection",
    "onlyalpha.transaction.projection_applier",
    "onlyalpha.transaction.recovery",
    "onlyalpha.transaction.state_hash",
    "onlyalpha.transaction.transaction",
)


def __getattr__(name: str) -> object:
    for module_name in _EXPORT_MODULES:
        module = import_module(module_name)
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value
    raise AttributeError(name)


__all__: list[str] = []
