from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.event.model import OnlyEvent
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


@dataclass(frozen=True, slots=True)
class OnlyObservedEventProjection:
    event_type: str
    source: str
    runtime_id: str
    cluster_id: str | None
    sequence: int
    payload_hash: str


def _projection(event: OnlyEvent) -> OnlyObservedEventProjection:
    payload = json.dumps(
        event.to_dict()["payload"], default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return OnlyObservedEventProjection(
        event.event_type.value,
        event.source.value,
        str(event.runtime_id),
        None if event.cluster_id is None else str(event.cluster_id),
        int(event.sequence),
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def test_recovery_suppresses_direct_categories_and_delivers_only_durable_transaction_facts(tmp_path: Path) -> None:
    engine_id = OnlyEngineId("recovery-direct-event-categories")
    engine_a = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    durable_records = reader.outbox_records(runtime_id)
    transactions = {item.execution_sequence: item for item in reader.records(runtime_id)}
    reader.close()
    durable_types = {item.event.event_type.value for item in durable_records}
    assert {
        "ORDER_FILLED",
        "POSITION_OPENED",
        "SETTLEMENT_UPDATED",
        "FEE_APPLICATION_RECORDED",
        "ACCOUNT_TRADE_APPLIED",
        "ACCOUNT_VALUED",
        "STRATEGY_TRADE_APPLIED",
        "STRATEGY_VALUATION_UPDATED",
    } <= durable_types
    assert all(
        item.published
        if transactions[item.key.execution_sequence].operation_kind.value == "ORDER_ACCEPTED"
        else not item.published
        for item in durable_records
    )

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_b.add_cluster(_same_bar_config(tmp_path))
    engine_b.initialize()
    runtime = engine_b.runtime_sessions[0].runtime
    snapshot = runtime.event_gate_snapshot
    suppressed_types = {item.event_type for item in snapshot.last_suppressed_events}
    assert {"BAR_RECEIVED", "BAR_VALIDATED", "MARKET_DATA_SNAPSHOT_READY"} <= suppressed_types
    assert {"ORDER_CREATED", "ORDER_SUBMITTED"} <= suppressed_types
    assert {"RISK_ACCEPTED", "RISK_RESERVATION_CREATED"} <= suppressed_types
    assert "ACCOUNT_CASH_RESERVED" in suppressed_types
    assert "STRATEGY_CASH_RESERVED" in suppressed_types
    assert snapshot.suppressed_direct_count >= len(snapshot.last_suppressed_events)
    assert runtime.event_bus.dispatch_results == ()

    suppressed_keys = {(item.event_type, item.source, item.sequence) for item in snapshot.last_suppressed_events}
    engine_b.start()
    dispatched = tuple(item.event for item in runtime.event_bus.dispatch_results)
    dispatched_keys = {(item.event_type.value, item.source.value, int(item.sequence)) for item in dispatched}
    assert not suppressed_keys.intersection(dispatched_keys)
    assert durable_types <= {item.event_type.value for item in dispatched}
    assert dispatched[-1].event_type.value == "RUNTIME_STARTED"
    observed = tuple(_projection(item) for item in dispatched)
    assert len(observed) == len(dispatched)
    assert len({(item.event_type, item.source, item.sequence, item.payload_hash) for item in observed}) == len(observed)
    engine_b.stop()
