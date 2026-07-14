import pytest

from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def test_default_primary_is_smallest_time_period(bar_1m, bar_3m, bar_15m) -> None:
    subscription = OnlyBarSubscription((bar_15m, bar_3m, bar_1m))
    assert subscription.primary_bar_type == bar_1m
    assert OnlyBarSubscription.from_dict(subscription.to_dict()) == subscription


def test_explicit_primary_overrides_default(bar_1m, bar_3m) -> None:
    assert OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m).primary_bar_type == bar_3m


def test_non_time_bar_requires_explicit_primary(instrument_id, bar_1m) -> None:
    volume = OnlyBarType(
        instrument_id,
        OnlyBarSpecification(100, OnlyBarAggregation.VOLUME, OnlyPriceType.LAST),
        OnlyAggregationSource.INTERNAL,
    )
    with pytest.raises(ValueError, match="explicit"):
        OnlyBarSubscription((bar_1m, volume))
    assert OnlyBarSubscription((bar_1m, volume), primary_bar_type=volume).primary_bar_type == volume


def test_subscription_rejects_primary_outside_set(bar_1m, bar_3m) -> None:
    with pytest.raises(ValueError, match="included"):
        OnlyBarSubscription((bar_1m,), primary_bar_type=bar_3m)
