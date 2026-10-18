"""Common valid routing against real Python Pipeline/Dispatcher, not Runtime admission."""

import json
from pathlib import Path
from uuid import UUID

from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, OnlyBarSubscriptionId
from tests.market_data.test_pipeline_dispatch import OnlyRecordingCluster, _system
from tests.market_data.test_rust_market_data_state_vectors import bar, kind

DATA = Path(__file__).resolve().parents[2] / "test-data/market-data-delivery"


def test_common_independent_routing_vectors(shanghai_calendar):
    for line in (DATA / "routing-v1.jsonl").read_text().splitlines():
        row = json.loads(line)
        registrations = []
        for sub in row["subscriptions"]:
            kinds = tuple(kind("600000.XSHG", window) for window in sub["types"])
            # The graph is supplied explicitly; no default random subscription identity.
            from onlyalpha.market_data.resolution import OnlyMarketDataConstructionGraph

            subscription = OnlyBarSubscription(
                kinds,
                OnlyMarketDataConstructionGraph(kinds, ()),
                None if sub["primary"] is None else kind("600000.XSHG", sub["primary"]),
                subscription_id=OnlyBarSubscriptionId(UUID(sub["id"])),
            )
            registrations.append(OnlyClusterBarSubscription(OnlyRecordingCluster(sub["cluster"]), subscription))
        pipeline, dispatcher, _ = _system(shanghai_calendar, tuple(registrations))
        for (window, end), expected in zip(row["operations"], row["expected"], strict=True):
            update = pipeline.process_bar(bar("600000.XSHG", window, end))
            result = dispatcher.dispatch(update)
            assert [str(item.cluster_id) for item in result if item.called] == expected
            assert all(item.succeeded for item in result)
