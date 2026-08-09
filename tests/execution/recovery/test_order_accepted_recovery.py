from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderRequestId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import (
    OnlyExecutionRecoveryService,
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyOrderAcceptedExecutionTransactionPlanner,
    OnlyOrderExecutionProjectionTarget,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeTransactionCoordinator,
    OnlyStrategyCashReservationExecutionProjectionTarget,
    OnlyStrategyLedgerExecutionProjectionTarget,
)
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlySqliteRuntimePersistenceStore,
)
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage
from tests.execution.support.execution_fault_injection import OnlyFailOnceExecutionProjectionTarget
from tests.integration_demo.environment import (
    ACCOUNT_ID,
    CLUSTER_ID,
    DAY_ONE,
    INSTRUMENT_ID,
    OnlyIntegrationEnvironment,
)


def _prepared_accepted() -> tuple[OnlyIntegrationEnvironment, OnlyBrokerOrderAcceptedUpdate, object]:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    environment.runtime._services.execution_event_buffer.begin()
    submitted = environment.runtime._services.order_service.submit(
        OnlyOrderRequest(
            OnlyOrderRequestId("accepted-recovery"),
            INSTRUMENT_ID,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1000"), 0),
            price=OnlyPrice(Decimal("10.00"), 2),
            offset=OnlyOffset.OPEN,
        ),
        CLUSTER_ID,
        OnlyAccountId(ACCOUNT_ID),
    )
    environment.runtime._services.execution_event_buffer.abort()
    assert submitted.order_id is not None
    broker = environment.runtime.broker_gateway
    assert broker is not None
    environment.runtime.clock.advance_by(1_000_000_000)
    broker.run_due()
    updates = environment.runtime._services.broker_inbound.drain()
    assert len(updates) == 1 and isinstance(updates[0], OnlyBrokerOrderAcceptedUpdate)
    update = updates[0]
    processor = environment.runtime.execution_processor
    scope = processor._resolve_position_scope(update)
    assert scope is not None
    decision = processor._resolve_execution_support(update, scope)
    context = environment.runtime._build_order_accepted_execution_planning_context(
        update,
        processor._processing_sequence + 1,
        scope,
        decision,
    )
    prepared = OnlyOrderAcceptedExecutionTransactionPlanner().prepare(context)
    assert environment.runtime.order_manager.require_snapshot(update.order_id).status is OnlyOrderStatus.SUBMITTED
    return environment, update, prepared


def _targets(environment: OnlyIntegrationEnvironment, ledger: OnlyInMemoryAppliedRuntimeProjectionLedger):
    return {
        OnlyRuntimeProjectionComponent.ORDER: OnlyOrderExecutionProjectionTarget(
            environment.runtime.order_manager,
            ledger,
        ),
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER: OnlyStrategyLedgerExecutionProjectionTarget(
            environment.runtime.strategy_ledger_manager,
            ledger,
        ),
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION: (
            OnlyStrategyCashReservationExecutionProjectionTarget(
                environment.runtime.strategy_ledger_manager,
                ledger,
            )
        ),
    }


@pytest.mark.parametrize("sqlite", (False, True))
def test_accepted_stored_before_projection_forward_recovers(
    tmp_path: Path,
    sqlite: bool,
) -> None:
    environment, update, prepared = _prepared_accepted()
    store = (
        OnlySqliteRuntimePersistenceStore(tmp_path / "accepted-stored.sqlite3")
        if sqlite
        else OnlyInMemoryRuntimePersistenceStore()
    )
    ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
    coordinator = OnlyRuntimeTransactionCoordinator(
        commit_port=store,
        query_port=store,
        projection_state_port=store,
        projection_applier=OnlyRuntimeProjectionApplier(_targets(environment, ledger)),
        now=lambda: prepared.prepared_at,
    )
    committed = store.commit(prepared, committed_at=prepared.prepared_at).transaction
    assert not committed.projection_ready

    recovered = OnlyExecutionRecoveryService(coordinator).recover(prepared.runtime_id)

    assert recovered.succeeded
    restored = store.get_by_transaction_id(prepared.transaction_id)
    assert restored is not None and restored.projection_ready
    assert environment.runtime.order_manager.require_snapshot(update.order_id).status is OnlyOrderStatus.ACCEPTED
    reservation = environment.runtime.strategy_ledger_manager.get_cash_reservation(
        prepared.projections[-1].after.key,
        update.order_id,
    )
    assert reservation is not None
    assert reservation.stage is OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED
    store.close()


@pytest.mark.parametrize(
    "component",
    (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
    ),
)
@pytest.mark.parametrize("fault_position", ("before", "after"))
def test_accepted_mid_projection_failure_resumes_exactly_once(
    component: OnlyRuntimeProjectionComponent,
    fault_position: str,
) -> None:
    environment, update, prepared = _prepared_accepted()
    store = OnlyInMemoryRuntimePersistenceStore()
    ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
    targets = _targets(environment, ledger)
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
    assert environment.runtime.order_manager.require_snapshot(update.order_id).status is OnlyOrderStatus.ACCEPTED
    assert len(ledger.records()) == 3
