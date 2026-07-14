"""Configured maximum notional rejects an otherwise valid Order."""

from decimal import Decimal

from accepted_order_demo import only_risk_demo_harness

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule

profile = OnlyRiskProfile(
    OnlyRiskProfileId("small-notional"),
    (OnlyMaxOrderNotionalRiskRule(OnlyMoney(Decimal("999.99"), OnlyCurrency("CNY", 2))),),
)
demo = only_risk_demo_harness(profile)
result = demo.orders.submit(demo.request, demo.cluster_id, demo.account_id)

if __name__ == "__main__":
    print(result.risk_rejection.code.value, result.created, len(demo.execution.submissions))
