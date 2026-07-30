from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyOrderExecutionState, OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.reducers import OnlyOrderTradeReducer
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def _state() -> OnlyOrderExecutionState:
    before = only_test_generic_t0_trade_planning_context().order_before
    return replace(
        before,
        quantity=OnlyQuantity(Decimal("1000"), 0),
        remaining_quantity=OnlyQuantity(Decimal("1000"), 0),
    )


def _trade(quantity: str, price: str, index: int):
    base = OnlyTradeExecutionTransactionPlanner._planned_trade(only_test_generic_t0_trade_planning_context())
    source_sequence = index + 100
    fill = replace(
        base.fill,
        trade_id=OnlyTradeId(f"trade-{index}"),
        quantity=OnlyQuantity(Decimal(quantity), 0),
        price=OnlyPrice(Decimal(price), 4),
        external_sequence=source_sequence,
    )
    return replace(
        base,
        trade_id=fill.trade_id,
        quantity=fill.quantity,
        price=fill.price,
        fill=fill,
        source_sequence=source_sequence,
    )


def test_exact_cumulative_value_survives_serialization_and_continued_fill() -> None:
    reducer = OnlyOrderTradeReducer()
    first = reducer.reduce(_state(), _trade("300", "10.0000", 1), projection_sequence=1).after
    restored = OnlyOrderExecutionState.from_dict(first.to_dict())
    second = reducer.reduce(restored, _trade("400", "10.1000", 2), projection_sequence=1).after
    final = reducer.reduce(second, _trade("300", "9.9000", 3), projection_sequence=1).after
    expected = (
        Decimal("300") * Decimal("10.0000") + Decimal("400") * Decimal("10.1000") + Decimal("300") * Decimal("9.9000")
    )
    assert final.status is OnlyOrderStatus.FILLED
    assert final.cumulative_price_quantity == expected == Decimal("10010.0000")
    assert final.average_fill_price == OnlyPrice(Decimal("10.0100"), 4)


def test_quantized_average_is_never_used_to_reconstruct_history() -> None:
    reducer = OnlyOrderTradeReducer()
    state = replace(
        _state(),
        quantity=OnlyQuantity(Decimal("3"), 0),
        remaining_quantity=OnlyQuantity(Decimal("3"), 0),
        price=OnlyPrice(Decimal("1.00"), 2),
    )
    first = reducer.reduce(state, _trade("1", "1.0001", 1), projection_sequence=1).after
    second = reducer.reduce(first, _trade("1", "1.0002", 2), projection_sequence=1).after
    final = reducer.reduce(second, _trade("1", "1.0003", 3), projection_sequence=1).after
    assert final.cumulative_price_quantity == Decimal("3.0006")
    assert final.average_fill_price == OnlyPrice(Decimal("1.0002"), 4)
