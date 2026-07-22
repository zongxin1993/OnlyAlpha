from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.order.exceptions import OnlyOrderScopeError


def test_two_clusters_share_runtime_manager_but_queries_are_scoped(make_runtime, order_request) -> None:
    runtime = make_runtime("runtime-orders", {"first": "400000.00", "second": "600000.00"})
    first = OnlyCluster(OnlyClusterConfig("first"))
    second = OnlyCluster(OnlyClusterConfig("second"))
    runtime.add_cluster("engine", first)
    runtime.add_cluster("engine", second)
    runtime.start()
    assert first.context is not None and second.context is not None
    submitted = first.context.orders.submit(order_request)
    assert first.context.orders.list_open() == (submitted.snapshot,)
    assert second.context.orders.list_open() == ()
    assert not hasattr(first.context.orders, "apply_fill")
    assert not hasattr(first.context.orders, "manager")
    assert not hasattr(first.context, "gateway")
    with pytest.raises(OnlyOrderScopeError):
        second.context.orders.require(submitted.order_id)
    with pytest.raises(FrozenInstanceError):
        submitted.snapshot.version = 99  # type: ignore[misc]


def test_each_runtime_starts_its_own_deterministic_order_sequence(make_runtime, order_request) -> None:
    snapshots = []
    for runtime_id in ("runtime-a", "runtime-b"):
        runtime = make_runtime(runtime_id)
        cluster = OnlyCluster(OnlyClusterConfig("cluster"))
        runtime.add_cluster("engine", cluster)
        runtime.start()
        assert cluster.context is not None
        snapshots.append(cluster.context.orders.submit(order_request).snapshot)
    assert str(snapshots[0].order_id).endswith("ORDER-000001")
    assert str(snapshots[1].order_id).endswith("ORDER-000001")
    assert snapshots[0].runtime_id != snapshots[1].runtime_id
