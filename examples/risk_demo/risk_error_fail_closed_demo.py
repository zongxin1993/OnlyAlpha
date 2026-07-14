"""Unexpected Rule failure becomes ERROR and fails closed."""

from accepted_order_demo import only_risk_demo_harness

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


class OnlyDemoFailingRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(OnlyRiskRuleMetadata(OnlyRiskRuleId("cluster.demo_failure"), OnlyRiskRuleScope.CLUSTER))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request, context
        raise RuntimeError("demo failure")


demo = only_risk_demo_harness(OnlyRiskProfile(OnlyRiskProfileId("error"), (OnlyDemoFailingRiskRule(),)))
result = demo.orders.submit(demo.request, demo.cluster_id, demo.account_id)

if __name__ == "__main__":
    print(result.risk_decision.outcome.value, result.created, len(demo.execution.submissions))
