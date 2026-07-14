"""Strategy-visible Risk state is immutable and read-only."""

from accepted_order_demo import only_risk_demo_harness

demo = only_risk_demo_harness()
before = demo.risk.get_snapshot(demo.cluster_id)
demo.orders.submit(demo.request, demo.cluster_id, demo.account_id)
after = demo.risk.get_snapshot(demo.cluster_id)

if __name__ == "__main__":
    print(before.version, after.version, after.reserved_quantity)
