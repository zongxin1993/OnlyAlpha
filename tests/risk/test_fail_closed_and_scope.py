from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import OnlyRiskOutcome, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskProfileId, OnlyRiskRuleId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


class OnlyBrokenClusterRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(OnlyRiskRuleMetadata(OnlyRiskRuleId("cluster.broken"), OnlyRiskRuleScope.CLUSTER))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request, context
        raise LookupError("required feed disappeared")


def test_rule_error_fails_closed_without_order_or_execution(build_harness, order_request) -> None:
    harness = build_harness(OnlyRiskProfile(OnlyRiskProfileId("broken"), (OnlyBrokenClusterRiskRule(),)))
    result = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)

    assert result.risk_decision is not None
    assert result.risk_decision.outcome is OnlyRiskOutcome.ERROR
    assert result.risk_error is not None and result.risk_error.exception_type == "LookupError"
    assert harness.manager.snapshot_all() == ()
    assert harness.execution.submissions == ()


def test_context_from_another_runtime_is_rejected(build_harness, order_request) -> None:
    harness = build_harness()
    context = harness.risk.make_evaluation_context(
        harness.cluster_id,
        harness.account_id,
        order_request.expire_time or harness.risk.get_snapshot(harness.cluster_id).ts_init,
    )
    object.__setattr__(context, "runtime_id", OnlyRuntimeId("other-runtime"))

    try:
        harness.risk.evaluate_order(order_request, context)
    except ValueError as error:
        assert "another Runtime" in str(error)
    else:
        raise AssertionError("cross-Runtime Risk context was accepted")


def test_unavailable_account_and_position_are_explicit_snapshot_flags(build_harness) -> None:
    harness = build_harness()
    snapshot = harness.risk.get_snapshot(harness.cluster_id)
    assert snapshot.quality_flags == ("ACCOUNT_RISK_UNAVAILABLE", "POSITION_RISK_UNAVAILABLE")
