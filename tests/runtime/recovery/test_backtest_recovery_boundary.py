from dataclasses import replace

import pytest

from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionRecoveryPlan,
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
    OnlyPreparedExecutionTransaction,
)
from onlyalpha.runtime.backtest.recovery_boundary import (
    OnlyBacktestRecoveryBoundary,
    OnlyBacktestRecoveryError,
    OnlyBacktestRecoveryPhase,
    OnlyBacktestRecoverySession,
)
from onlyalpha.runtime.backtest.result_progress import OnlyBacktestBarCompletion
from onlyalpha.runtime.checkpoint.model import OnlyBacktestReplayCursor
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction
from tests.execution.test_causal_execution_recovery import _update

_SOURCE = OnlyMarketDataSourceId("recovery-source")
_VERSION = OnlyDataVersion("recovery-version")
_TIME = OnlyTimestamp.from_unix_nanos(1_000)


def _cursor() -> OnlyBacktestReplayCursor:
    return OnlyBacktestReplayCursor(_SOURCE, _VERSION, None, 0, None, 0)


def _boundary(sequence: int, update_id: str, *, ts_event: OnlyTimestamp = _TIME) -> OnlyBacktestRecoveryBoundary:
    return OnlyBacktestRecoveryBoundary(
        _SOURCE,
        _VERSION,
        OnlyMarketDataUpdateId(update_id),
        sequence,
        ts_event,
    )


def _completion(boundary: OnlyBacktestRecoveryBoundary) -> OnlyBacktestBarCompletion:
    return OnlyBacktestBarCompletion(
        boundary.update_id,
        boundary.source_id,
        boundary.data_version,
        boundary.source_sequence,
        boundary.source_sequence,
        OnlyMarketDataProcessingStatus.APPLIED,
        boundary.ts_event,
        boundary.source_sequence,
    )


def _resolved_execution_session() -> OnlyExecutionRecoverySession:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    return OnlyExecutionRecoverySession(OnlyExecutionRecoveryPlan(prepared.runtime_id, 1, 0, ()))


def _matching_execution_session() -> tuple[OnlyExecutionRecoverySession, OnlyPreparedExecutionTransaction]:
    store = OnlyInMemoryRuntimePersistenceStore()
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store.commit(prepared, committed_at=prepared.prepared_at)
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        prepared.runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=0,
    )
    return OnlyExecutionRecoverySession(plan), prepared


def test_completion_requires_entered_exact_identity() -> None:
    session = OnlyBacktestRecoverySession(_resolved_execution_session(), _cursor())
    boundary = _boundary(1, "update-1")
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_NOT_ENTERED"):
        session.observe_completion(_completion(boundary))

    for field, value in (
        ("update_id", OnlyMarketDataUpdateId("wrong-update")),
        ("source_sequence", 2),
        ("data_version", OnlyDataVersion("wrong-version")),
    ):
        selected = OnlyBacktestRecoverySession(_resolved_execution_session(), _cursor())
        selected.enter_boundary(boundary)
        completion = _completion(boundary)
        with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_IDENTITY_MISMATCH"):
            selected.observe_completion(replace(completion, **{field: value}))


def test_tail_can_cross_boundaries_and_same_timestamp_updates_remain_distinct() -> None:
    execution, prepared = _matching_execution_session()
    session = OnlyBacktestRecoverySession(execution, _cursor())
    first = _boundary(1, "same-time-a")
    second = _boundary(2, "same-time-b")

    session.enter_boundary(first)
    session.observe_completion(_completion(first))
    assert session.phase is OnlyBacktestRecoveryPhase.MATCHING_PERSISTED_TAIL
    assert session.current_boundary is None

    session.enter_boundary(second)
    decision = execution.decide(_update(prepared), prepared)
    assert decision.entry is not None
    execution.resolve_persisted(
        decision.entry.execution_sequence,
        OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED,
    )
    assert session.phase is OnlyBacktestRecoveryPhase.TAIL_RESOLVED_BOUNDARY_OPEN
    assert session.current_boundary == second
    session.observe_completion(_completion(second))

    assert session.phase is OnlyBacktestRecoveryPhase.BOUNDARY_COMPLETED
    assert session.final_boundary == second
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_PROCESS_AFTER_BOUNDARY_COMPLETE"):
        session.enter_boundary(_boundary(3, "too-late"))


def test_tail_resolved_does_not_complete_an_open_boundary() -> None:
    session = OnlyBacktestRecoverySession(_resolved_execution_session(), _cursor())
    boundary = _boundary(1, "open-boundary")
    session.enter_boundary(boundary)

    assert session.phase is OnlyBacktestRecoveryPhase.TAIL_RESOLVED_BOUNDARY_OPEN
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_INCOMPLETE"):
        session.require_boundary_completed()

    session.observe_completion(_completion(boundary))
    session.require_boundary_completed()


def test_enter_rejects_open_duplicate_scope_and_non_advancing_boundaries() -> None:
    boundary = _boundary(1, "update-1")
    open_session = OnlyBacktestRecoverySession(_resolved_execution_session(), _cursor())
    open_session.enter_boundary(boundary)
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_ALREADY_OPEN"):
        open_session.enter_boundary(_boundary(2, "update-2"))

    execution, _ = _matching_execution_session()
    duplicate_session = OnlyBacktestRecoverySession(execution, _cursor())
    duplicate_session.enter_boundary(boundary)
    duplicate_session.observe_completion(_completion(boundary))
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_IDENTITY_MISMATCH"):
        duplicate_session.enter_boundary(boundary)

    wrong_scope = OnlyBacktestRecoverySession(_resolved_execution_session(), _cursor())
    with pytest.raises(OnlyBacktestRecoveryError, match="RECOVERY_BOUNDARY_IDENTITY_MISMATCH"):
        wrong_scope.enter_boundary(
            OnlyBacktestRecoveryBoundary(
                OnlyMarketDataSourceId("wrong-source"),
                _VERSION,
                OnlyMarketDataUpdateId("wrong-scope"),
                1,
                _TIME,
            )
        )
