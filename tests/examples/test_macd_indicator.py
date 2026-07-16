from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from onlyalpha.config import OnlyRunConfig
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator import OnlyIndicatorId, OnlyMacdIndicator, OnlyMacdIndicatorConfig, OnlyMacdSnapshot


def _bar(config: OnlyRunConfig, index: int, close: str) -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
    value = Decimal(close)
    return OnlyBar(
        bar_type=config.strategies[0]
        .common.subscriptions.instrument_bars[0]
        .bar_specification.to_bar_type(config.reference_data.instruments[0].instrument_id),
        open=OnlyPrice(value, 2),
        high=OnlyPrice(value, 2),
        low=OnlyPrice(value, 2),
        close=OnlyPrice(value, 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        ts_event=start + timedelta(minutes=1),
        ts_init=start + timedelta(minutes=1),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.CONTINUOUS,
    )


def test_macd_decimal_values_warmup_and_duplicate_idempotency() -> None:
    config = OnlyRunConfig.load("examples/backtest_macd/config.yaml")
    bar_type = (
        config.strategies[0]
        .common.subscriptions.instrument_bars[0]
        .bar_specification.to_bar_type(config.reference_data.instruments[0].instrument_id)
    )
    indicator = OnlyMacdIndicator(
        OnlyMacdIndicatorConfig(OnlyIndicatorId("macd-test"), bar_type, 2, 3, 2, warmup_bars=3)
    )
    values = [indicator.update(_bar(config, index, close), ()) for index, close in enumerate(("1", "2", "3"))]
    assert all(isinstance(item, OnlyMacdSnapshot) for item in values)
    final = values[-1]
    assert isinstance(final, OnlyMacdSnapshot)
    assert final.ready
    assert final.dif == Decimal("0.305555555556")
    assert final.dea == Decimal("0.240740740741")
    assert final.histogram == Decimal("0.129629629630")
    assert indicator.update(_bar(config, 2, "3"), ()) == final
    assert indicator.snapshot is not None and indicator.snapshot.samples == 3


def test_macd_rejects_out_of_order_and_open_bars() -> None:
    config = OnlyRunConfig.load("examples/backtest_macd/config.yaml")
    bar_type = (
        config.strategies[0]
        .common.subscriptions.instrument_bars[0]
        .bar_specification.to_bar_type(config.reference_data.instruments[0].instrument_id)
    )
    indicator = OnlyMacdIndicator(
        OnlyMacdIndicatorConfig(OnlyIndicatorId("macd-order"), bar_type, 2, 3, 2, warmup_bars=3)
    )
    indicator.update(_bar(config, 2, "3"), ())
    with pytest.raises(ValueError, match="out-of-order"):
        indicator.update(_bar(config, 1, "2"), ())
    open_bar = replace(_bar(config, 3, "4"), is_closed=False)
    with pytest.raises(ValueError, match="closed"):
        indicator.update(open_bar, ())
