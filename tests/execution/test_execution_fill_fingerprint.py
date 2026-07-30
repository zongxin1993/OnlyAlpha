from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import only_execution_fill_payload_fingerprint
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_fill_fingerprint_is_canonical_and_payload_sensitive() -> None:
    update = only_test_generic_t0_trade_planning_context().update
    baseline = only_execution_fill_payload_fingerprint(update)
    reordered = replace(update, fill=replace(update.fill, metadata={"b": "2", "a": "1"}))
    reordered_again = replace(update, fill=replace(update.fill, metadata={"a": "1", "b": "2"}))
    assert only_execution_fill_payload_fingerprint(reordered) == only_execution_fill_payload_fingerprint(
        reordered_again
    )
    changes = (
        replace(update, fill=replace(update.fill, quantity=OnlyQuantity(Decimal("1"), 0))),
        replace(update, fill=replace(update.fill, price=OnlyPrice(Decimal("10.01"), 2))),
        replace(update, source_sequence=update.source_sequence + 1),
        replace(update, fill=replace(update.fill, liquidity_side=OnlyLiquiditySide.MAKER)),
        replace(update, ts_init=type(update.ts_init)(update.ts_init.unix_nanos + 1)),
    )
    assert all(only_execution_fill_payload_fingerprint(item) != baseline for item in changes)
    assert len(baseline) == 64
