from dataclasses import replace

import pytest

from onlyalpha.broker import OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId
from onlyalpha.execution import (
    OnlyExecutionRecoveryDecisionKind,
    OnlyExecutionRecoveryError,
    OnlyExecutionRecoveryPhase,
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction
from tests.execution.test_causal_execution_recovery import _update


def _resolved_session() -> tuple[OnlyInMemoryRuntimePersistenceStore, OnlyExecutionRecoverySession]:
    store = OnlyInMemoryRuntimePersistenceStore()
    first = only_test_generic_t0_cash_buy_open_transaction()
    store.commit(first, committed_at=first.prepared_at)
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        first.runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=0,
    )
    session = OnlyExecutionRecoverySession(plan)
    decision = session.decide(_update(first), first)
    assert decision.entry is not None
    session.resolve_persisted(
        decision.entry.execution_sequence,
        OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED,
    )
    return store, session


def test_tail_resolved_returns_commit_continuation_and_records_contiguous_sequences() -> None:
    store, session = _resolved_session()

    for sequence in range(2, 5):
        prepared = only_test_generic_t0_cash_buy_open_transaction(
            trade_id=OnlyTradeId(f"continuation-trade-{sequence}"),
            update_id=OnlyBrokerUpdateId(f"continuation-update-{sequence}"),
            fill_index=sequence,
        )
        decision = session.decide(_update(prepared), prepared)
        assert decision.kind is OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION
        assert decision.entry is None
        store.commit(prepared, committed_at=prepared.prepared_at)
        store.mark_projection_ready(prepared.runtime_id, sequence, projected_at=prepared.prepared_at)
        ready = store.get_by_sequence(prepared.runtime_id, sequence)
        assert ready is not None
        session.record_continuation(ready)

    assert session.phase is OnlyExecutionRecoveryPhase.TAIL_RESOLVED
    assert tuple(item.execution_sequence for item in session.continuations) == (2, 3, 4)


@pytest.mark.parametrize("invalid_sequence", (1, 3))
def test_continuation_rejects_non_contiguous_sequence(invalid_sequence: int) -> None:
    store, session = _resolved_session()
    prepared = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("invalid-sequence-trade"),
        update_id=OnlyBrokerUpdateId("invalid-sequence-update"),
        fill_index=2,
    )
    store.commit(prepared, committed_at=prepared.prepared_at)
    store.mark_projection_ready(prepared.runtime_id, 2, projected_at=prepared.prepared_at)
    ready = store.get_by_sequence(prepared.runtime_id, 2)
    assert ready is not None

    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_CONTINUATION_SEQUENCE_MISMATCH"):
        session.record_continuation(
            replace(
                ready,
                execution_sequence=invalid_sequence,
                fact=replace(ready.fact, execution_sequence=invalid_sequence),
            )
        )

    assert session.phase is OnlyExecutionRecoveryPhase.FAILED


def test_continuation_rejects_not_ready_and_wrong_runtime() -> None:
    store, not_ready_session = _resolved_session()
    prepared = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("not-ready-trade"),
        update_id=OnlyBrokerUpdateId("not-ready-update"),
        fill_index=2,
    )
    not_ready = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_CONTINUATION_TRANSACTION_NOT_READY"):
        not_ready_session.record_continuation(not_ready)

    store, wrong_scope_session = _resolved_session()
    prepared = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("wrong-scope-trade"),
        update_id=OnlyBrokerUpdateId("wrong-scope-update"),
        fill_index=2,
    )
    store.commit(prepared, committed_at=prepared.prepared_at)
    store.mark_projection_ready(prepared.runtime_id, 2, projected_at=prepared.prepared_at)
    ready = store.get_by_sequence(prepared.runtime_id, 2)
    assert ready is not None
    wrong_runtime = OnlyRuntimeId("wrong-runtime")
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_CONTINUATION_SCOPE_MISMATCH"):
        wrong_scope_session.record_continuation(
            replace(ready, runtime_id=wrong_runtime, fact=replace(ready.fact, runtime_id=wrong_runtime))
        )


def test_failed_session_rejects_all_later_decisions_and_records() -> None:
    store, session = _resolved_session()
    prepared = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("failed-trade"),
        update_id=OnlyBrokerUpdateId("failed-update"),
        fill_index=2,
    )
    committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    with pytest.raises(OnlyExecutionRecoveryError):
        session.record_continuation(committed)
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_SESSION_FAILED"):
        session.decide(_update(prepared), prepared)
    with pytest.raises(OnlyExecutionRecoveryError, match="RECOVERY_SESSION_FAILED"):
        session.record_continuation(committed)
