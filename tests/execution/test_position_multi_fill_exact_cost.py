from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionManager, OnlySettlementBucket
from tests.position.test_position_component import RUNTIME, trade


def test_position_preserves_exact_open_price_quantity_across_fills_and_legacy_decode() -> None:
    manager = OnlyPositionManager(RUNTIME)
    manager.apply_trade(trade(1, OnlyOrderSide.BUY, "1", "10", bucket=OnlySettlementBucket.SETTLED))
    manager.apply_trade(trade(2, OnlyOrderSide.BUY, "2", "11", bucket=OnlySettlementBucket.SETTLED))
    snapshot = manager.list_open()[0]
    assert snapshot.cumulative_open_price_quantity == Decimal("32")
    assert snapshot.average_open_price is not None
    assert snapshot.average_open_price.value == Decimal("10.67")

    restored = type(snapshot).from_dict(snapshot.to_dict())
    assert restored.cumulative_open_price_quantity == Decimal("32")
    legacy = snapshot.to_dict()
    legacy.pop("cumulative_open_price_quantity")
    legacy_restored = type(snapshot).from_dict(legacy)
    assert legacy_restored.cumulative_open_price_quantity == Decimal("32.01")
