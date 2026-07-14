from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import (
    OnlyRiskOutcome,
    OnlyRiskRejectionCode,
    OnlyRiskRuleMode,
    OnlyRiskRuleScope,
)
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.pipeline import OnlyRiskPipeline
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


class OnlyRecordingRiskRule(OnlyRiskRule):
    def __init__(self, rule_id: str, scope: OnlyRiskRuleScope, order: int, calls: list[str]) -> None:
        super().__init__(OnlyRiskRuleMetadata(OnlyRiskRuleId(rule_id), scope, order=order))
        self.calls = calls

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request, context
        self.calls.append(str(self.rule_id))
        return self._accept()


class OnlyRejectingRiskRule(OnlyRiskRule):
    def __init__(self, *, mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING) -> None:
        super().__init__(
            OnlyRiskRuleMetadata(
                OnlyRiskRuleId("cluster.reject"),
                OnlyRiskRuleScope.CLUSTER,
                mode,
                1,
            )
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request, context
        return self._reject(OnlyRiskRejectionCode.MAXIMUM_QUANTITY_EXCEEDED, "rejected")


class OnlyExplodingRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(
            OnlyRiskRuleMetadata(
                OnlyRiskRuleId("cluster.explodes"),
                OnlyRiskRuleScope.CLUSTER,
            )
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request, context
        raise RuntimeError("rule exploded")


def test_pipeline_orders_by_scope_then_explicit_order_then_rule_id(build_harness, order_request) -> None:
    harness = build_harness()
    context = harness.risk.make_evaluation_context(
        harness.cluster_id,
        harness.account_id,
        order_request.expire_time
        or __import__("onlyalpha.domain.time", fromlist=["OnlyTimestamp"]).OnlyTimestamp.from_unix_nanos(1),
    )
    calls: list[str] = []
    pipeline = OnlyRiskPipeline(
        (
            OnlyRecordingRiskRule("cluster.b", OnlyRiskRuleScope.CLUSTER, 10, calls),
            OnlyRecordingRiskRule("runtime.a", OnlyRiskRuleScope.RUNTIME, 99, calls),
            OnlyRecordingRiskRule("cluster.a", OnlyRiskRuleScope.CLUSTER, 10, calls),
        )
    )
    result = pipeline.evaluate(order_request, context)
    assert result.decision.outcome is OnlyRiskOutcome.ACCEPT
    assert calls == ["runtime.a", "cluster.a", "cluster.b"]


def test_first_enforcing_rejection_stops_and_observing_rejection_does_not(build_harness, order_request) -> None:
    harness = build_harness()
    from onlyalpha.domain.time import OnlyTimestamp

    context = harness.risk.make_evaluation_context(
        harness.cluster_id, harness.account_id, OnlyTimestamp.from_unix_nanos(1)
    )
    observing = OnlyRiskPipeline((OnlyRejectingRiskRule(mode=OnlyRiskRuleMode.OBSERVING),))
    observed = observing.evaluate(order_request, context).decision
    assert observed.is_accepted and len(observed.observations) == 1
    enforcing = OnlyRiskPipeline((OnlyRejectingRiskRule(),))
    rejected = enforcing.evaluate(order_request, context).decision
    assert rejected.is_rejected and rejected.rejection is not None


def test_rule_exception_is_captured_as_fail_closed_error(build_harness, order_request) -> None:
    from onlyalpha.domain.time import OnlyTimestamp

    harness = build_harness()
    context = harness.risk.make_evaluation_context(
        harness.cluster_id, harness.account_id, OnlyTimestamp.from_unix_nanos(1)
    )
    decision = OnlyRiskPipeline((OnlyExplodingRiskRule(),)).evaluate(order_request, context).decision
    assert decision.outcome is OnlyRiskOutcome.ERROR
    assert decision.error is not None and decision.error.exception_type == "RuntimeError"
