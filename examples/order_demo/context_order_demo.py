from examples.order_demo.common import only_demo_components
from examples.runtime_context_demo.common import only_demo_runtime
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig


def main() -> None:
    runtime = only_demo_runtime("context-order-demo")
    cluster = OnlyCluster(OnlyClusterConfig("demo"))
    runtime.add_cluster("engine", cluster)
    runtime.start()
    assert cluster.context is not None
    request = only_demo_components()[-1]
    result = cluster.context.orders.submit(request)
    print(result.snapshot.to_json())
    print("visible_orders=", len(cluster.context.orders.list_open()))
    print("has_manager=", hasattr(cluster.context.orders, "manager"))
    runtime.close()


if __name__ == "__main__":
    main()
