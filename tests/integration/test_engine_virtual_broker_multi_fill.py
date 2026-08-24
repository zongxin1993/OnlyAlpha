from decimal import Decimal

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillPlanStatus

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction import OnlyRuntimeOperationKind
from tests.integration.virtual_multi_fill_support import only_virtual_multi_fill_config


def test_engine_runs_300_400_300_as_three_formal_transactions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("virtual-multi-fill"), tmp_path))
    engine.add_cluster(only_virtual_multi_fill_config(tmp_path))
    result = engine.run()
    assert result.status == "COMPLETED", result.failures
    runtime = engine.runtime_sessions[0].runtime
    runtime_id = engine.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine.config.engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    records = reader.ready_records(runtime_id)
    assert tuple(item.operation_kind for item in records) == (
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.TRADE_FILL,
        OnlyRuntimeOperationKind.TRADE_FILL,
    )
    trades = tuple(item for item in records if item.operation_kind is OnlyRuntimeOperationKind.TRADE_FILL)
    assert tuple(item.fact.fill_index for item in trades) == (1, 2, 3)
    assert tuple(item.execution_sequence for item in records) == (1, 2, 3, 4)
    assert all(item.projection_ready for item in records)
    order = result.runtime_results[0].orders[0]
    assert order.status is OnlyOrderStatus.FILLED
    assert order.filled_quantity.value == Decimal("1000")
    assert isinstance(runtime.broker_gateway, OnlyVirtualBrokerGateway)
    assert tuple(item.fill.quantity.value for item in runtime.broker_gateway.query_trades(order.account_id)) == (
        Decimal("300"),
        Decimal("400"),
        Decimal("300"),
    )
    assert runtime.broker_gateway.fill_plan_store.require(order.order_id).status is OnlyVirtualFillPlanStatus.COMPLETED
    assert runtime.risk_service.reservations.snapshot_active() == ()
    reader.close()
