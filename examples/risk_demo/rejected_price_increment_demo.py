"""Invalid tick is rejected without Order or Execution side effects."""

from dataclasses import replace
from decimal import Decimal

from accepted_order_demo import only_risk_demo_harness

from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.value import OnlyPrice

demo = only_risk_demo_harness()
request = replace(
    demo.request,
    request_id=OnlyOrderRequestId("risk-demo-bad-tick"),
    price=OnlyPrice(Decimal("10.03"), 2),
)
result = demo.orders.submit(request, demo.cluster_id, demo.account_id)

if __name__ == "__main__":
    print(result.risk_rejection.code.value, len(demo.manager.snapshot_all()), len(demo.execution.submissions))
