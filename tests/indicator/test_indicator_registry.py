from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator import only_default_indicator_factories
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest
from onlyalpha.indicator.identifiers import MACD, RSI, OnlyIndicatorId
from onlyalpha.indicator.macd import OnlyMacdIndicator, OnlyMacdIndicatorFactory, OnlyMacdSnapshot
from onlyalpha.indicator.rsi import OnlyRsiSnapshot


def _bar_type():
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    spec = config.cluster.factors[0].subscriptions.instrument_bars[0]
    return spec.bar_specification.to_bar_type(spec.instrument_id)


def _bar(index: int, close: str) -> OnlyBar:
    bar_type = _bar_type()
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
    value = Decimal(close)
    return OnlyBar(
        bar_type=bar_type,
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


def test_registry_creates_macd_with_defaults_and_special_parameters() -> None:
    registry = only_default_indicator_factories()
    default = registry.create(OnlyIndicatorCreateRequest(MACD, OnlyIndicatorId("default"), _bar_type(), {}))
    special = registry.create(
        OnlyIndicatorCreateRequest(
            MACD,
            OnlyIndicatorId("special"),
            _bar_type(),
            {"fast_period": 2, "slow_period": 3, "signal_period": 2, "warmup_bars": 3},
        )
    )
    assert isinstance(default, OnlyMacdIndicator)
    assert default.config.fast_period == 12
    assert isinstance(special, OnlyMacdIndicator)
    assert special.config.fast_period == 2
    for index, close in enumerate(("1", "2", "3")):
        special.update_bar(_bar(index, close))
    assert isinstance(special.snapshot(), OnlyMacdSnapshot)
    assert special.ready
    assert special.canonical_score().ready
    special.reset()
    assert not special.ready
    assert special.warmup_progress.samples == 0


def test_registry_creates_default_rsi_and_rejects_unknown_or_duplicate_factory() -> None:
    registry = only_default_indicator_factories()
    rsi = registry.create(OnlyIndicatorCreateRequest(RSI, OnlyIndicatorId("rsi"), _bar_type(), {}))
    for index in range(14):
        rsi.update_bar(_bar(index, str(index + 1)))
    assert isinstance(rsi.snapshot(), OnlyRsiSnapshot)
    assert rsi.ready
    with pytest.raises(ValueError, match="unknown indicator type"):
        registry.create(
            OnlyIndicatorCreateRequest(type(RSI)("vendor.custom"), OnlyIndicatorId("custom"), _bar_type(), {})
        )
    with pytest.raises(ValueError, match="duplicate indicator factory"):
        registry.register(OnlyMacdIndicatorFactory())
