"""Stable white-box digest of Runtime-owned execution authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from onlyalpha.domain.base import OnlyDomainModel
from tests.integration_demo.environment import OnlyIntegrationEnvironment


@dataclass(frozen=True, slots=True)
class OnlyTestRuntimeAuthorityDigest:
    orders: object
    positions: object
    allocations: object
    accounts: object
    account_reservations: object
    ledgers: object
    strategy_reservations: object
    risk_state: object
    risk_reservations: object
    settlement: object
    fees: object
    deduplication: object
    sequences: object
    journal: object
    event_buffer: object
    event_bus: object
    reconciliation: object


def only_test_runtime_authority_digest(env: OnlyIntegrationEnvironment) -> OnlyTestRuntimeAuthorityDigest:
    runtime = env.runtime
    orders = runtime.order_manager
    positions = runtime.position_manager
    allocations = runtime.allocation_manager
    accounts = runtime.account_manager
    ledgers = runtime.strategy_ledger_manager
    risk = runtime.risk_service
    settlement = runtime.settlement_manager
    fees = runtime.fee_manager
    processor = runtime.execution_processor
    return OnlyTestRuntimeAuthorityDigest(
        orders=_stable(vars(orders)),
        positions=_stable(
            (
                positions.snapshot_all(),
                positions.closed(),
                positions._trade_fingerprints,
                positions._cycles,
                positions._event_sequence,
                vars(positions._repository),
            )
        ),
        allocations=_stable(
            (
                allocations.snapshot_all(),
                allocations.closed(),
                allocations.unallocated(),
                allocations._trade_fingerprints,
                allocations._cycles,
                vars(allocations._repository),
            )
        ),
        accounts=_stable(
            (
                accounts.list_accounts(),
                accounts._trade_ids,
                accounts._fee_ids,
                accounts._cash_change_ids,
                accounts._valuation_versions,
                accounts._event_sequence,
                vars(accounts._repository),
            )
        ),
        account_reservations=_stable(accounts._reservation_manager._reservations),
        ledgers=_stable(
            (
                ledgers.list_ledgers(),
                ledgers._scope_index,
                ledgers._trade_fingerprints,
                ledgers._fee_ids,
                ledgers._cash_flow_ids,
                ledgers._valuation_versions,
                ledgers._event_sequence,
                ledgers._equity_sequence,
                ledgers._equity_timelines,
                vars(ledgers._repository),
            )
        ),
        strategy_reservations=_stable(
            {str(key.to_json()): manager.snapshots() for key, manager in ledgers._reservations.items()}
        ),
        risk_state=_stable(
            (
                risk._state._snapshots,
                risk._state._snapshot_versions,
                risk._state._rejection_counts,
                risk._state._decisions,
                risk._state._rule_state,
                risk._requests,
                risk._audits,
                vars(risk._kill_switch),
                risk._event_sequence,
                risk._audit_sequence,
            )
        ),
        risk_reservations=_stable(
            (
                risk.reservations.snapshot_all(),
                risk.reservations._sequence,
                risk.reservations._reservation_id_by_order_id,
            )
        ),
        settlement=_stable((settlement._pending, settlement.records)),
        fees=_stable((fees.records, fees._instruction_keys)),
        deduplication=_stable(vars(processor._deduplicator)),
        sequences=_stable((processor._processing_sequence, vars(processor._sequences), processor._trade_instructions)),
        journal=_stable(
            (
                runtime.committed_execution_query.records(),
                vars(processor._execution_commits),
            )
        ),
        event_buffer=_stable(vars(processor._events)),
        event_bus=_stable(runtime.event_bus.dispatch_results),
        reconciliation=_stable(runtime.execution_reconciliation_queue.requests()),
    )


def _stable(value: object) -> object:
    if isinstance(value, OnlyDomainModel):
        return _json(value.to_dict())
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return tuple(sorted((str(_stable(key)), _stable(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_stable(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((str(_stable(item)), _stable(item)) for item in value))
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if hasattr(value, "__dict__"):
        return _stable(vars(value))
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = ["OnlyTestRuntimeAuthorityDigest", "only_test_runtime_authority_digest"]
