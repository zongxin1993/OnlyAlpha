from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.position import OnlyPositionAllocationManager, OnlySettlementBucket
from tests.position.test_position_component import CLUSTER_A, RUNTIME, trade


def test_allocation_preserves_exact_open_price_quantity_across_fills_and_round_trip() -> None:
    manager = OnlyPositionAllocationManager(RUNTIME)
    manager.apply_trade(trade(1, OnlyOrderSide.BUY, "1", "10", bucket=OnlySettlementBucket.SETTLED))
    manager.apply_trade(trade(2, OnlyOrderSide.BUY, "2", "11", bucket=OnlySettlementBucket.SETTLED))
    snapshot = manager.list_by_cluster(CLUSTER_A)[0]
    assert snapshot.cumulative_open_price_quantity == Decimal("32")
    assert snapshot.average_open_price is not None
    assert snapshot.average_open_price.value == Decimal("10.67")
    assert type(snapshot).from_dict(snapshot.to_dict()) == snapshot
