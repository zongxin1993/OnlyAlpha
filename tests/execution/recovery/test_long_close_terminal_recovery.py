import pytest

from onlyalpha.execution import (
    OnlyExecutionOutboxPublisher,
    OnlyExecutionProcessingStatus,
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoveryService,
    OnlyExecutionRecoverySession,
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyOrderExecutionProjectionTarget,
    OnlyPositionReservationExecutionProjectionTarget,
    OnlyRiskExecutionProjectionTarget,
    OnlyRiskReservationExecutionProjectionTarget,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeTransactionCoordinator,
    OnlyTerminalExecutionTransactionPlanner,
)
from onlyalpha.position.enums import OnlyPositionReservationState
from onlyalpha.risk.enums import OnlyRiskReservationState
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceExecutionProjectionTarget,
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.execution.test_long_close_terminal_planner import _terminal_update


def _prepared_terminal(terminal: str):  # type: ignore[no-untyped-def]
    environment, context, update = _terminal_update(terminal)
    runtime = environment.runtime
    processor = runtime.execution_processor
    scope = processor._resolve_position_scope(update)
    assert scope is not None
    decision = processor._resolve_execution_support(update, scope)
    planning = runtime._build_terminal_execution_planning_context(
        update,
        processor._processing_sequence + 1,
        scope,
        decision,
    )
    return environment, context, update, OnlyTerminalExecutionTransactionPlanner().prepare(planning)


def test_terminal_committed_before_projection_replays_through_existing_causal_session() -> None:
    environment, _, update, prepared = _prepared_terminal("CANCELLED")
    runtime = environment.runtime
    store = runtime._runtime_persistence_store
    assert store is not None
    committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    plan = OnlyExecutionRecoveryPlanBuilder(store).build(
        prepared.runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=committed.execution_sequence - 1,
    )
    session = OnlyExecutionRecoverySession(plan)

    replayed = runtime.execution_processor.replay(update, session)

    assert replayed.status is OnlyExecutionProcessingStatus.APPLIED
    session.require_tail_resolved()
    restored = store.get_by_sequence(prepared.runtime_id, committed.execution_sequence)
    assert restored is not None and restored.projection_ready
    reservation = runtime.position_reservation_manager.get(update.order_id)
    assert reservation is not None and reservation.state is OnlyPositionReservationState.RELEASED
    risk = runtime.risk_service.reservations.get_for_order(update.order_id)
    assert risk is not None and risk.state is OnlyRiskReservationState.RELEASED


@pytest.mark.parametrize(
    "component",
    (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
    ),
)
@pytest.mark.parametrize("fault_position", ("before", "after"))
def test_terminal_mid_projection_failure_forward_recovers_exactly_once(
    component: OnlyRuntimeProjectionComponent,
    fault_position: str,
) -> None:
    environment, _, update, prepared = _prepared_terminal("CANCELLED")
    runtime = environment.runtime
    store = runtime._runtime_persistence_store
    assert store is not None
    ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
    targets = {
        OnlyRuntimeProjectionComponent.ORDER: OnlyOrderExecutionProjectionTarget(runtime.order_manager, ledger),
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION: OnlyPositionReservationExecutionProjectionTarget(
            runtime.position_reservation_manager,
            ledger,
        ),
        OnlyRuntimeProjectionComponent.RISK_RESERVATION: OnlyRiskReservationExecutionProjectionTarget(
            runtime.risk_service,
            ledger,
        ),
        OnlyRuntimeProjectionComponent.RISK: OnlyRiskExecutionProjectionTarget(runtime.risk_service, ledger),
    }
    targets[component] = OnlyFailOnceExecutionProjectionTarget(
        targets[component],
        fail_before=fault_position == "before",
        fail_after=fault_position == "after",
    )
    coordinator = OnlyRuntimeTransactionCoordinator(
        commit_port=store,
        query_port=store,
        projection_state_port=store,
        projection_applier=OnlyRuntimeProjectionApplier(targets),
        now=lambda: prepared.prepared_at,
    )
    service = OnlyExecutionRecoveryService(coordinator)
    store.commit(prepared, committed_at=prepared.prepared_at)

    assert not service.recover(prepared.runtime_id).succeeded
    assert service.recover(prepared.runtime_id).succeeded

    transaction = store.get_by_transaction_id(prepared.transaction_id)
    assert transaction is not None and transaction.projection_ready
    order = runtime.order_manager.require_snapshot(update.order_id)
    assert order.filled_quantity.value == 300 and order.remaining_quantity.value == 700
    reservation = runtime.position_reservation_manager.get(update.order_id)
    assert reservation is not None
    assert reservation.consumed_quantity is not None and reservation.consumed_quantity.value == 300
    assert reservation.released_quantity is not None and reservation.released_quantity.value == 700
    risk_reservation = runtime.risk_service.reservations.get_for_order(update.order_id)
    assert risk_reservation is not None
    assert risk_reservation.consumed_quantity is not None and risk_reservation.consumed_quantity.value == 300
    assert risk_reservation.released_quantity is not None and risk_reservation.released_quantity.value == 700
    snapshot = runtime.risk_service.get_snapshot(order.cluster_id)
    assert snapshot.active_order_count == snapshot.cluster_active_order_count == 0


def test_terminal_outbox_failure_retries_without_reprojecting_authority() -> None:
    environment, _, update = _terminal_update("CANCELLED")
    runtime = environment.runtime
    store = runtime._runtime_persistence_store
    assert store is not None
    assert runtime._services.execution_outbox_publisher.publish_pending(update.runtime_id).remaining == 0
    terminal = runtime.execution_processor.process(update)
    assert terminal.status is OnlyExecutionProcessingStatus.APPLIED
    before = (
        runtime.order_manager.require_snapshot(update.order_id),
        runtime.position_reservation_manager.get(update.order_id),
        runtime.risk_service.reservations.get_for_order(update.order_id),
    )
    fault_store = OnlyFailOnceRuntimePersistenceStore(
        store,
        OnlyTestRuntimePersistenceFault.OUTBOX_MARK_PUBLISHED,
    )
    publisher = OnlyExecutionOutboxPublisher(
        fault_store,
        runtime._services.event_router,
        lambda: update.ts_init,
    )

    first = publisher.publish_pending(update.runtime_id)
    second = publisher.publish_pending(update.runtime_id)

    assert first.failed == 1 and first.remaining > 0
    assert second.failed == 0 and second.remaining == 0
    assert before == (
        runtime.order_manager.require_snapshot(update.order_id),
        runtime.position_reservation_manager.get(update.order_id),
        runtime.risk_service.reservations.get_for_order(update.order_id),
    )
