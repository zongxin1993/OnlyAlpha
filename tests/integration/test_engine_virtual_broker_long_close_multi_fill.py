from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillPlanStatus

from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyCommittedExecutionFact
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.position.enums import OnlyPositionReservationState
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import OnlyRiskExecutionProjection
from tests.integration.virtual_multi_fill_support import only_virtual_multi_fill_config


@pytest.mark.parametrize("same_bar", (False, True), ids=("cross-bar", "same-bar"))
def test_engine_virtual_broker_runs_complete_long_close_multi_fill(tmp_path, same_bar: bool) -> None:  # type: ignore[no-untyped-def]
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId(f"virtual-long-close-{'same' if same_bar else 'cross'}-bar"), tmp_path)
    )
    engine.add_cluster(only_virtual_multi_fill_config(tmp_path, same_bar=same_bar, long_close=True))

    result = engine.run()

    assert result.status == "COMPLETED", result.failures
    runtime = engine.runtime_sessions[0].runtime
    sell = next(item for item in result.runtime_results[0].orders if item.side is OnlyOrderSide.SELL)
    assert sell.status is OnlyOrderStatus.FILLED
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(
        engine.config.engine_id, runtime.config.runtime_id
    )
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    records = reader.transactions_for_order(runtime.config.runtime_id, sell.order_id)
    assert tuple(item.operation_kind for item in records) == (
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.TRADE_FILL,
    )
    trade_records = tuple(item for item in records if item.operation_kind is OnlyRuntimeOperationKind.TRADE_FILL)
    assert all(isinstance(item.fact, OnlyCommittedExecutionFact) for item in trade_records)
    facts = tuple(item.fact for item in trade_records if isinstance(item.fact, OnlyCommittedExecutionFact))
    assert tuple(item.fill_index for item in facts) == (1, 2, 3)
    assert tuple(item.fill_quantity.value for item in facts) == (Decimal("300"), Decimal("400"), Decimal("300"))
    assert tuple(item.position_quantity_after for item in facts) == (
        Decimal("700"),
        Decimal("300"),
        Decimal("0"),
    )
    assert facts[-1].position_cumulative_open_price_quantity_after == 0
    reservation = runtime.position_reservation_manager.get(sell.order_id)
    assert reservation is not None
    assert reservation.state is OnlyPositionReservationState.CONSUMED
    assert reservation.remaining_quantity.value == 0
    risk_reservation = runtime.risk_service.reservations.get_for_order(sell.order_id)
    assert risk_reservation is not None
    assert risk_reservation.state is OnlyRiskReservationState.CONSUMED
    assert risk_reservation.remaining_quantity.value == 0
    final_risk = next(item for item in trade_records[-1].projections if isinstance(item, OnlyRiskExecutionProjection))
    assert final_risk.after.active_order_count == 0
    assert isinstance(runtime.broker_gateway, OnlyVirtualBrokerGateway)
    plan = runtime.broker_gateway.fill_plan_store.require(sell.order_id)
    assert plan.status is OnlyVirtualFillPlanStatus.COMPLETED
    trades = tuple(
        item for item in runtime.broker_gateway.query_trades(sell.account_id) if item.fill.order_id == sell.order_id
    )
    assert tuple(item.fill.quantity.value for item in trades) == (Decimal("300"), Decimal("400"), Decimal("300"))
    if same_bar:
        assert trades[0].fill.ts_event == trades[1].fill.ts_event
    else:
        assert len({item.fill.ts_event for item in trades}) == 3
    reader.close()
