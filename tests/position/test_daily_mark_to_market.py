from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.market import OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyMultiplier, OnlyPrice
from onlyalpha.position.enums import OnlySettlementBucket
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionSettlementFact
from tests.position.test_position_component import CNY, RUNTIME, trade


def _open(manager: OnlyPositionManager) -> None:
    manager.apply_trade(trade(1, OnlyOrderSide.BUY, "2", "100", bucket=OnlySettlementBucket.SETTLED))


def _settlement(manager: OnlyPositionManager, identifier: str, price: str, timestamp: int):
    key = manager.list_open()[0].key
    return manager.apply_settlement(
        OnlyPositionSettlementFact(
            key,
            OnlyReferencePriceFact(
                identifier,
                key.instrument_id,
                OnlyReferencePriceKind.SETTLEMENT,
                OnlyPrice(Decimal(price), 2),
                OnlyTimestamp(timestamp).to_datetime(),
                OnlyTimestamp(timestamp).to_datetime(),
                "TEST",
                timestamp,
                "fixture-v1",
            ),
            OnlyMultiplier(Decimal("1"), 0),
            CNY,
        )
    )


def test_daily_mark_to_market_reset_and_checkpoint_continuation() -> None:
    uninterrupted = OnlyPositionManager(RUNTIME)
    _open(uninterrupted)
    first, realized = _settlement(uninterrupted, "settlement-1", "110", 2_000)
    assert realized.amount == Decimal("20.00")
    assert first.average_open_price == OnlyPrice(Decimal("110"), 2)
    duplicate, duplicate_delta = _settlement(uninterrupted, "settlement-1", "110", 2_000)
    assert duplicate == first
    assert duplicate_delta.amount == 0
    try:
        _settlement(uninterrupted, "settlement-1", "111", 2_000)
    except ValueError as exc:
        assert str(exc) == "POSITION_SETTLEMENT_FACT_ID_CONFLICT"
    else:
        raise AssertionError("settlement identity collision must fail closed")

    checkpoint = uninterrupted.capture_checkpoint()
    restored = OnlyPositionManager(RUNTIME)
    restored.restore_checkpoint(checkpoint)

    expected, expected_delta = _settlement(uninterrupted, "settlement-2", "105", 3_000)
    actual, actual_delta = _settlement(restored, "settlement-2", "105", 3_000)
    assert actual == expected
    assert actual_delta == expected_delta
    assert actual.realized_pnl.amount == Decimal("10.00")
