from collections.abc import Iterator
from pathlib import Path

import pytest

from onlyalpha.broker import OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionRecoveryDecisionKind,
    OnlyExecutionRecoveryError,
    OnlyExecutionRecoveryPhase,
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
    OnlyPreparedRuntimeTransaction,
)
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlyRuntimePersistenceStorePort,
    OnlySqliteRuntimePersistenceStore,
)
from tests.execution.factories.transaction_factory import (
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_rehash,
)


@pytest.fixture(params=("memory", "sqlite"))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[OnlyRuntimePersistenceStorePort]:
    selected: OnlyRuntimePersistenceStorePort
    if request.param == "memory":
        selected = OnlyInMemoryRuntimePersistenceStore()
    else:
        selected = OnlySqliteRuntimePersistenceStore(tmp_path / "causal-recovery.sqlite3")
    yield selected
    selected.close()


def test_store_returns_original_prepared_and_committed_recovery_record(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction

    assert store.recovery_records(prepared.runtime_id, after_sequence=0)[0].prepared == prepared
    assert (
        store.get_recovery_record_by_update(
            prepared.runtime_id,
            prepared.fact_draft.gateway_id,
            prepared.account_id,
            prepared.fact_draft.broker_update_id,
        )
        == store.recovery_records(prepared.runtime_id, after_sequence=0)[0]
    )
    assert store.recovery_records(prepared.runtime_id, after_sequence=0)[0].committed == committed


def test_session_resolves_ready_then_unprojected_in_strict_causal_order(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=OnlyBrokerUpdateId("update-2"),
        fill_index=2,
    )
    first_committed = store.commit(first, committed_at=first.prepared_at).transaction
    store.mark_projection_ready(first.runtime_id, 1, projected_at=first.prepared_at)
    store.commit(second, committed_at=second.prepared_at)
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        first.runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=0,
    )
    session = OnlyExecutionRecoverySession(plan)

    decision = session.decide(_update(first), first)
    assert decision.kind is OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY
    entry = decision.entry
    assert entry is not None
    assert entry.execution_sequence == first_committed.execution_sequence
    session.resolve_persisted(entry.execution_sequence, OnlyExecutionRecoveryResolution.READY_REHYDRATED)
    decision = session.decide(_update(second), second)
    assert decision.kind is OnlyExecutionRecoveryDecisionKind.RECOVER_UNPROJECTED
    entry = decision.entry
    assert entry is not None
    session.resolve_persisted(entry.execution_sequence, OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED)

    assert session.phase is OnlyExecutionRecoveryPhase.TAIL_RESOLVED
    assert session.tail_resolved
    assert session.ready_rehydrated_count == 1
    assert session.unprojected_recovered_count == 1


def test_session_rejects_missing_conflicting_and_out_of_order_transactions(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=OnlyBrokerUpdateId("update-2"),
        fill_index=2,
    )
    store.commit(first, committed_at=first.prepared_at)
    store.commit(second, committed_at=second.prepared_at)
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        first.runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=0,
    )

    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH"):
        OnlyExecutionRecoverySession(plan).decide(_update(second), second)

    conflict = only_test_rehash(
        first,
        prepared_at=OnlyTimestamp.from_unix_nanos(first.prepared_at.unix_nanos + 1),
    )
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_PREPARED_TRANSACTION_MISMATCH"):
        OnlyExecutionRecoverySession(plan).decide(_update(first), conflict)

    missing = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("missing-trade"),
        update_id=OnlyBrokerUpdateId("missing-update"),
    )
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_TRANSACTION_MISSING"):
        OnlyExecutionRecoverySession(plan).decide(_update(missing), missing)


def test_session_resolves_three_ready_and_multiple_unprojected_entries_strictly(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    prepared_values = tuple(
        only_test_generic_t0_cash_buy_open_transaction(
            trade_id=OnlyTradeId(f"long-tail-trade-{index}"),
            update_id=OnlyBrokerUpdateId(f"long-tail-update-{index}"),
            fill_index=index,
        )
        for index in range(1, 6)
    )
    for prepared in prepared_values:
        store.commit(prepared, committed_at=prepared.prepared_at)
    for sequence in (1, 2, 3):
        store.mark_projection_ready(
            prepared_values[0].runtime_id,
            sequence,
            projected_at=prepared_values[sequence - 1].prepared_at,
        )
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        prepared_values[0].runtime_id,
        checkpoint_sequence=2,
        covered_execution_sequence=0,
    )
    session = OnlyExecutionRecoverySession(plan)

    for sequence, prepared in enumerate(prepared_values, start=1):
        decision = session.decide(_update(prepared), prepared)
        entry = decision.entry
        assert entry is not None
        resolution = (
            OnlyExecutionRecoveryResolution.READY_REHYDRATED
            if sequence <= 3
            else OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED
        )
        session.resolve_persisted(entry.execution_sequence, resolution)

    assert session.ready_rehydrated_count == 3
    assert session.unprojected_recovered_count == 2


def _update(prepared: OnlyPreparedRuntimeTransaction) -> OnlyBrokerTradeUpdate:
    fact = prepared.fact_draft
    fill = OnlyOrderFill(
        fact.trade_id,
        fact.order_id,
        fact.fill_price,
        fact.fill_quantity,
        fact.ts_event,
        fact.ts_init,
        external_sequence=fact.source_sequence,
    )
    return OnlyBrokerTradeUpdate(
        runtime_id=fact.runtime_id,
        gateway_id=fact.gateway_id,
        account_id=fact.account_id,
        update_id=fact.broker_update_id,
        source_sequence=fact.source_sequence,
        ts_event=fact.ts_event,
        ts_init=fact.ts_init,
        correlation_id=fact.correlation_id,
        causation_id=fact.causation_id,
        order_id=fact.order_id,
        fill=fill,
    )
