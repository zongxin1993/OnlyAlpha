"""A first accepted Order immediately reduces capacity for the next Order."""

from dataclasses import replace
from decimal import Decimal

from accepted_order_demo import only_risk_demo_harness

from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule

profile = OnlyRiskProfile(
    OnlyRiskProfileId("reservation"),
    (OnlyMaxOrderNotionalRiskRule(OnlyMoney(Decimal("1500.00"), OnlyCurrency("CNY", 2))),),
)
demo = only_risk_demo_harness(profile)
first = demo.orders.submit(demo.request, demo.cluster_id, demo.account_id)
second_request = replace(demo.request, request_id=OnlyOrderRequestId("risk-demo-request-2"))
second = demo.orders.submit(second_request, demo.cluster_id, demo.account_id)

if __name__ == "__main__":
    print(first.risk_decision.outcome.value, second.risk_rejection.code.value)
