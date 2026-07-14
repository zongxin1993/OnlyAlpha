"""The same intent is evaluated against isolated Cluster Profiles."""

from decimal import Decimal

from accepted_order_demo import only_risk_demo_harness

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule


def profile(name: str, maximum: str) -> OnlyRiskProfile:
    return OnlyRiskProfile(
        OnlyRiskProfileId(name),
        (OnlyMaxOrderNotionalRiskRule(OnlyMoney(Decimal(maximum), OnlyCurrency("CNY", 2))),),
    )


cluster_a = only_risk_demo_harness(profile("cluster-a", "500.00"), cluster_id="cluster-a", runtime_id="runtime-a")
cluster_b = only_risk_demo_harness(profile("cluster-b", "2000.00"), cluster_id="cluster-b", runtime_id="runtime-b")
result_a = cluster_a.orders.submit(cluster_a.request, cluster_a.cluster_id, cluster_a.account_id)
result_b = cluster_b.orders.submit(cluster_b.request, cluster_b.cluster_id, cluster_b.account_id)

if __name__ == "__main__":
    print(result_a.risk_decision.outcome.value, result_b.risk_decision.outcome.value)
