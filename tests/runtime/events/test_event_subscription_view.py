from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.subscription_view import OnlyEventBusSubscriptionView


def test_subscription_view_exposes_observation_but_no_write_or_dispatch() -> None:
    view = OnlyEventBusSubscriptionView(OnlyEventBus())
    subscription = view.subscribe("TEST", lambda event: None)
    assert view.pending_count() == 0
    assert view.failures == ()
    assert view.dispatch_results == ()
    assert view.dropped_events == ()
    assert view.unsubscribe(subscription.subscription_id)
    for forbidden in ("publish", "publish_many", "dispatch", "drain", "close"):
        assert not hasattr(view, forbidden)
