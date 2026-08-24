from decimal import Decimal

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerGateway

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.transaction import OnlyRuntimeOperationKind
from tests.integration.virtual_multi_fill_support import only_virtual_multi_fill_config


def test_engine_commits_two_same_bar_fills_in_deterministic_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("virtual-same-bar-multi-fill"), tmp_path))
    engine.add_cluster(only_virtual_multi_fill_config(tmp_path, same_bar=True))
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
    assert trades[0].fact.ts_event == trades[1].fact.ts_event
    assert trades[0].transaction_id != trades[1].transaction_id
    assert trades[0].fact.source_sequence + 1 == trades[1].fact.source_sequence
    assert isinstance(runtime.broker_gateway, OnlyVirtualBrokerGateway)
    trades = runtime.broker_gateway.query_trades(result.runtime_results[0].orders[0].account_id)
    assert tuple(item.fill.quantity.value for item in trades) == (Decimal("300"), Decimal("400"), Decimal("300"))
    reader.close()
