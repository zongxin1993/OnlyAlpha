from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity


def test_bar_has_complete_time_volume_and_revision_semantics(instrument_id, cny) -> None:
    spec = OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    bar_type = OnlyBarType(instrument_id, spec, OnlyAggregationSource.EXTERNAL)
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    bar = OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal("10.10"), 2),
        low=OnlyPrice(Decimal("9.90"), 2),
        close=OnlyPrice(Decimal("10.05"), 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=OnlyQuantity(Decimal("1000"), 0),
        turnover=OnlyMoney(Decimal("1000.00"), cny),
        trade_count=10,
        open_interest=None,
        bar_start=start,
        bar_end=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        ts_event=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        ts_init=datetime(2026, 1, 5, 1, 31, 1, tzinfo=UTC),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.REGULAR,
    )
    assert bar.contains(start) and not bar.contains(bar.bar_end)
    assert OnlyBar.from_json(bar.to_json()) == bar
