import ast
import inspect

from onlyalpha.execution import (
    OnlyCommittedRuntimeTransaction,
    OnlyRuntimeTransactionQueryPort,
    fill_identity,
    only_runtime_transaction_id,
)
from onlyalpha.execution.reducers import trade_state


def test_order_reducer_remains_pure_and_fill_identity_has_no_runtime_dependency() -> None:
    reducer_imports = {
        node.module or ""
        for node in ast.walk(ast.parse(inspect.getsource(trade_state)))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("store" in name or "manager" in name or "event.bus" in name for name in reducer_imports)
    fill_imports = {
        node.module or ""
        for node in ast.walk(ast.parse(inspect.getsource(fill_identity)))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith("onlyalpha.runtime") for name in fill_imports)


def test_durable_fill_query_and_immutable_transaction_contract_remain_public() -> None:
    assert hasattr(OnlyRuntimeTransactionQueryPort, "get_by_fill_identity")
    assert hasattr(OnlyRuntimeTransactionQueryPort, "transactions_for_order")
    assert OnlyCommittedRuntimeTransaction.__dataclass_params__.frozen
    assert only_runtime_transaction_id(
        runtime_id=__import__("onlyalpha.domain.identifiers", fromlist=["OnlyRuntimeId"]).OnlyRuntimeId("runtime"),
        gateway_id=__import__("onlyalpha.broker", fromlist=["OnlyBrokerGatewayId"]).OnlyBrokerGatewayId("gateway"),
        account_id=__import__("onlyalpha.domain.identifiers", fromlist=["OnlyAccountId"]).OnlyAccountId("account"),
        broker_update_id=__import__("onlyalpha.broker", fromlist=["OnlyBrokerUpdateId"]).OnlyBrokerUpdateId("update"),
        trade_id=__import__("onlyalpha.domain.identifiers", fromlist=["OnlyTradeId"]).OnlyTradeId("trade"),
    ).startswith("ETX-")


def test_fill_identity_and_fingerprint_do_not_use_process_local_hash_or_repr() -> None:
    source = inspect.getsource(fill_identity)
    assert "hash(" not in source
    assert "repr(" not in source
    assert "sha256" in source
