from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from onlyalpha_plugin_indicators.registration import registrations

from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest
from onlyalpha.indicator.identifiers import (
    ATR,
    BOLLINGER,
    EMA,
    MACD,
    ROLLING_RETURN,
    ROLLING_VOLATILITY,
    RSI,
    SMA,
    ZSCORE,
    OnlyIndicatorId,
    OnlyIndicatorTypeId,
)
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry

BAR_TYPE = OnlyBarType(
    OnlyInstrumentId.parse("TEST.XNAS"),
    OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
    OnlyAggregationSource.EXTERNAL,
)


def _bar(index: int, close: str) -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
    value = Decimal(close)
    return OnlyBar(
        bar_type=BAR_TYPE,
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


def _indicator(indicator_type: OnlyIndicatorTypeId, **parameters: object):
    registry = OnlyIndicatorFactoryRegistry()
    for registration in registrations():
        if registration.backend.value != "TRADING" or hasattr(registration.provider, "indicator_type"):
            registry.register(registration)
    return registry.create(
        OnlyIndicatorCreateRequest(indicator_type, OnlyIndicatorId(str(indicator_type).lower()), BAR_TYPE, parameters)
    )


@pytest.mark.parametrize(
    ("indicator_type", "expected"),
    (
        (EMA, {"value": "5.375000000000"}),
        (SMA, {"value": "4.666666666667"}),
        (RSI, {"value": "100.000000000000"}),
        (ATR, {"atr": "2.333333333333", "normalized_atr": "0.291666666667"}),
        (
            BOLLINGER,
            {"middle": "4.666666666667", "upper": "9.655543182365", "lower": "-0.322209849032"},
        ),
        (ROLLING_RETURN, {"value": "7.000000000000"}),
        (ROLLING_VOLATILITY, {"value": "2.494438257849"}),
        (ZSCORE, {"value": "1.336306209562"}),
    ),
)
def test_standard_indicator_observable_semantics(indicator_type, expected) -> None:
    indicator = _indicator(indicator_type, period=3)
    assert not indicator.ready
    for index, close in enumerate(("1", "2", "4", "8")):
        indicator.update_bar(_bar(index, close))
    snapshot = dict(indicator.snapshot().to_dict())
    assert {name: snapshot[name] for name in expected} == expected
    if indicator_type == RSI:
        assert indicator.snapshot().zone.value == "OVERBOUGHT"  # type: ignore[attr-defined]
    assert snapshot["samples"] == 4
    assert snapshot["ts_event_ns"] == 1767576840000000000
    assert indicator.ready
    duplicate = indicator.capture_checkpoint()
    indicator.update_bar(_bar(3, "999"))
    assert indicator.capture_checkpoint() == duplicate
    with pytest.raises(ValueError, match="out-of-order"):
        indicator.update_bar(_bar(2, "4"))
    restored = _indicator(indicator_type, period=3)
    restored.restore_checkpoint(duplicate)
    indicator.update_bar(_bar(4, "16"))
    restored.update_bar(_bar(4, "16"))
    assert restored.snapshot() == indicator.snapshot()
    assert restored.definition.fingerprint == indicator.definition.fingerprint
    indicator.reset()
    assert not indicator.ready
    assert indicator.warmup_progress.samples == 0


def test_macd_observable_semantics_and_checkpoint_continuation() -> None:
    parameters = {"fast_period": 2, "slow_period": 3, "signal_period": 2, "warmup_bars": 3}
    indicator = _indicator(MACD, **parameters)
    for index, close in enumerate(("1", "2", "4", "8")):
        indicator.update_bar(_bar(index, close))
    assert dict(indicator.snapshot().to_dict()) == {
        "indicator_id": "macd",
        "ts_event_ns": 1767576840000000000,
        "samples": 4,
        "dif": "1.032407407407",
        "dea": "0.805555555555",
        "histogram": "0.453703703704",
        "cross_state": "NONE",
        "ready": True,
    }
    checkpoint = indicator.capture_checkpoint()
    indicator.update_bar(_bar(3, "999"))
    assert indicator.capture_checkpoint() == checkpoint
    with pytest.raises(ValueError, match="out-of-order"):
        indicator.update_bar(_bar(2, "4"))
    restored = _indicator(MACD, **parameters)
    restored.restore_checkpoint(checkpoint)
    indicator.update_bar(_bar(4, "16"))
    restored.update_bar(_bar(4, "16"))
    assert restored.snapshot() == indicator.snapshot()
    assert restored.definition.fingerprint == indicator.definition.fingerprint
    indicator.reset()
    assert not indicator.ready
    assert indicator.warmup_progress.samples == 0


def test_all_official_definitions_have_exact_identity_and_defaults() -> None:
    definitions = tuple(
        item.type_definition
        for item in registrations()
        if item.backend.value == "TRADING" and item.type_definition.semantic_version == "1"
    )
    retained = tuple(
        item
        for item in definitions
        if hasattr(
            next(
                registration.provider
                for registration in registrations()
                if registration.backend.value == "TRADING" and registration.type_definition is item
            ),
            "indicator_type",
        )
    )
    assert len(retained) == 9
    assert {item.semantic_version for item in retained} == {"1"}
    assert {item.type_id for item in retained} == {
        "onlyalpha.indicator.ema",
        "onlyalpha.indicator.sma",
        "onlyalpha.indicator.rsi",
        "onlyalpha.indicator.atr",
        "onlyalpha.indicator.bollinger",
        "onlyalpha.indicator.rolling_return",
        "onlyalpha.indicator.rolling_volatility",
        "onlyalpha.indicator.zscore",
        "onlyalpha.indicator.macd",
    }
