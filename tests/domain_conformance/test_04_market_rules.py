from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyAssetClass, OnlyOrderSide
from onlyalpha.market.models import OnlyInstrumentReferenceSnapshot, OnlyMarketProfileId, OnlyQuantityRule


def test_same_equity_can_use_different_rules(equity, buy_request) -> None:
    reference = OnlyInstrumentReferenceSnapshot(
        str(equity.instrument_id),
        OnlyAssetClass.EQUITY,
        str(equity.venue),
        OnlyMarketProfileId.GENERIC_T0_CASH,
        str(equity.settlement_currency),
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        "test",
        "1",
        "fingerprint",
        quantity_step=Decimal("0.001"),
        lot_size=Decimal("100"),
    )
    assert (
        OnlyQuantityRule(True, buy_lot_required=True).validate(reference, OnlyOrderSide.BUY, buy_request.quantity.value)
        == "BUY_LOT_REQUIRED"
    )
    assert OnlyQuantityRule(True).validate(reference, OnlyOrderSide.BUY, buy_request.quantity.value) is None
