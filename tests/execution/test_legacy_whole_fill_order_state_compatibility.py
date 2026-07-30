from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.execution import OnlyOrderExecutionState
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context

_NEW_FIELDS = {
    "fill_count",
    "cumulative_price_quantity",
    "last_trade_id",
    "historical_fill_identity_missing",
}


def test_legacy_unfilled_snapshot_derives_empty_fill_authority() -> None:
    snapshot = only_test_generic_t0_trade_planning_context().order_before
    payload = snapshot.to_dict()
    for field in _NEW_FIELDS:
        payload.pop(field)
    restored = OnlyOrderExecutionState.from_dict(payload)
    assert restored.fill_count == 0
    assert restored.cumulative_price_quantity == 0
    assert restored.last_trade_id is None


def test_legacy_whole_fill_snapshot_derives_exact_compatible_authority() -> None:
    context = only_test_generic_t0_trade_planning_context()
    prepared = __import__("onlyalpha.execution", fromlist=["OnlyTradeExecutionTransactionPlanner"])
    transaction = prepared.OnlyTradeExecutionTransactionPlanner().prepare(context)
    order_after = transaction.projections[0].after
    payload = order_after.to_dict()
    for field in _NEW_FIELDS:
        payload.pop(field)
    restored = OnlyOrderSnapshot.from_dict(payload)
    assert restored.fill_count == 1
    assert restored.cumulative_price_quantity == restored.average_fill_price.value * restored.filled_quantity.value  # type: ignore[union-attr]
    assert restored.last_trade_id is None and restored.historical_fill_identity_missing
