from decimal import Decimal

import pytest

from onlyalpha.domain.market import (
    OnlyBarSemantic,
    OnlyBarType,
    OnlyTickCountBarFormation,
    OnlyTradeInputType,
    OnlyTradeSemantic,
    OnlyVolumeBarFormation,
)
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionRecipe,
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
)
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def _subscription(
    source: OnlyBarType, *targets: OnlyBarType, primary: OnlyBarType | None = None
) -> OnlyBarSubscription:
    edges = tuple(
        OnlyMarketDataConstructionEdge(
            source,
            target,
            OnlyBarConstructionRecipe.derived(target.semantic, source.semantic, algorithm_id="TIME_BAR"),
        )
        for target in targets
        if target.semantic.is_fixed_duration
    )
    graph = OnlyMarketDataConstructionGraph((source,), edges)
    return OnlyBarSubscription((source, *targets), graph, primary_bar_type=primary)


def test_default_primary_is_smallest_time_period(bar_1m, bar_3m, bar_15m) -> None:
    subscription = _subscription(bar_1m, bar_15m, bar_3m)
    assert subscription.primary_bar_type == bar_1m
    assert OnlyBarSubscription.from_dict(subscription.to_dict()) == subscription


def test_explicit_primary_overrides_default(bar_1m, bar_3m) -> None:
    assert _subscription(bar_1m, bar_3m, primary=bar_3m).primary_bar_type == bar_3m


def test_non_time_bar_requires_explicit_primary(instrument_id, bar_1m) -> None:
    volume = OnlyBarType(
        instrument_id,
        OnlyBarSemantic(OnlyVolumeBarFormation(Decimal("100"))),
    )
    with pytest.raises(ValueError, match="exactly match"):
        _subscription(bar_1m, volume)
    native_volume = OnlyMarketDataConstructionGraph((bar_1m, volume), ())
    assert OnlyBarSubscription((bar_1m, volume), native_volume, primary_bar_type=volume).primary_bar_type == volume


def test_subscription_rejects_primary_outside_set(bar_1m, bar_3m) -> None:
    with pytest.raises(ValueError, match="included"):
        OnlyBarSubscription((bar_1m,), OnlyMarketDataConstructionGraph((bar_1m,), ()), primary_bar_type=bar_3m)


def test_subscription_loader_rejects_unknown_or_malformed_fields(bar_1m) -> None:
    payload = OnlyBarSubscription((bar_1m,), OnlyMarketDataConstructionGraph((bar_1m,), ())).to_dict()
    payload["bar_types"] = [*payload["bar_types"], "ignored"]  # type: ignore[misc]
    with pytest.raises(ValueError, match="BAR_SUBSCRIPTION_INVALID"):
        OnlyBarSubscription.from_dict(payload)


def test_trade_root_subscription_roundtrips_with_bar_delivery(instrument_id) -> None:
    source = OnlyTradeInputType(instrument_id)
    target = OnlyBarType(instrument_id, OnlyBarSemantic(OnlyTickCountBarFormation(3)))
    graph = OnlyMarketDataConstructionGraph(
        (source,),
        (
            OnlyMarketDataConstructionEdge(
                source,
                target,
                OnlyBarConstructionRecipe.derived(target.semantic, OnlyTradeSemantic(), algorithm_id="TICK_BAR"),
            ),
        ),
    )
    subscription = OnlyBarSubscription((target,), graph, primary_bar_type=target)

    assert OnlyBarSubscription.from_dict(subscription.to_dict()) == subscription


def test_trade_root_subscription_rejects_instrument_scope_mismatch(instrument_id) -> None:
    source = OnlyTradeInputType(instrument_id)
    other = type(instrument_id).parse("OTHER.SIM")
    target = OnlyBarType(other, OnlyBarSemantic(OnlyTickCountBarFormation(3)))
    graph = OnlyMarketDataConstructionGraph((source, target), ())
    with pytest.raises(ValueError, match="instrument scope mismatch"):
        OnlyBarSubscription((target,), graph, primary_bar_type=target)
