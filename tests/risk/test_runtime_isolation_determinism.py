from examples.runtime_context_demo.common import (
    only_demo_bar,
    only_demo_bar_types,
    only_demo_runtime,
)
from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def test_runtime_risk_state_and_reservations_are_isolated(order_request) -> None:
    runtime_a = only_demo_runtime("risk-isolation-a")
    runtime_b = only_demo_runtime("risk-isolation-b")
    cluster_a = OnlyDemoCluster(OnlyClusterConfig("same-cluster"))
    cluster_b = OnlyDemoCluster(OnlyClusterConfig("same-cluster"))
    runtime_a.add_cluster("engine", cluster_a)
    runtime_b.add_cluster("engine", cluster_b)
    runtime_a.start()
    runtime_b.start()
    assert cluster_a.context is not None and cluster_b.context is not None

    accepted = cluster_a.context.orders.submit(order_request)

    assert accepted.created
    assert cluster_a.context.risk.snapshot().reserved_quantity == order_request.quantity.value
    assert cluster_b.context.risk.snapshot().reserved_quantity == 0
    assert len(cluster_a.context.orders.list_open()) == 1
    assert cluster_b.context.orders.list_open() == ()
    runtime_a.close()
    runtime_b.close()


def test_risk_snapshot_is_refreshed_before_bar_callback() -> None:
    runtime = only_demo_runtime("risk-pre-bar")
    bar_1m, _ = only_demo_bar_types()
    cluster = OnlyDemoCluster(OnlyClusterConfig("risk-cluster"), OnlyBarSubscription((bar_1m,)))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    assert cluster.context is not None
    initial = cluster.context.risk.snapshot()

    runtime.process_bar(only_demo_bar(bar_1m, 0))

    updated = cluster.context.risk.snapshot()
    assert len(cluster.records) == 1
    assert updated.version > initial.version
    assert updated.ts_event.unix_nanos == cluster.records[0].ts_event_ns
    assert not hasattr(cluster.context.risk, "evaluate_order")
    assert not hasattr(cluster.context.risk, "reserve_order")
    runtime.close()


def test_identical_replay_produces_identical_decision_and_reservation_id(build_harness, order_request) -> None:
    first = build_harness(runtime_id="same-runtime", cluster_id="same-cluster")
    second = build_harness(runtime_id="same-runtime", cluster_id="same-cluster")

    first_result = first.orders.submit(order_request, OnlyClusterId("same-cluster"), OnlyAccountId("risk-account"))
    second_result = second.orders.submit(order_request, OnlyClusterId("same-cluster"), OnlyAccountId("risk-account"))

    assert first_result.risk_decision == second_result.risk_decision
    assert first_result.order_id == second_result.order_id
    assert first.risk.reservations.snapshot_all() == second.risk.reservations.snapshot_all()
