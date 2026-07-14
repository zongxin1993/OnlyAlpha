"""Deterministic first-rejection Risk Pipeline."""

from dataclasses import dataclass

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskErrorInfo, OnlyRiskObservation
from onlyalpha.risk.enums import OnlyRiskRuleMode, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule

_ONLY_SCOPE_ORDER = {
    OnlyRiskRuleScope.SYSTEM: 0,
    OnlyRiskRuleScope.RUNTIME: 1,
    OnlyRiskRuleScope.ACCOUNT: 2,
    OnlyRiskRuleScope.INSTRUMENT: 3,
    OnlyRiskRuleScope.CLUSTER: 4,
}


@dataclass(frozen=True, slots=True)
class OnlyRiskPipelineConfig:
    first_rejection_stops: bool = True

    def __post_init__(self) -> None:
        if not self.first_rejection_stops:
            raise ValueError("Only the deterministic first-rejection policy is implemented")


@dataclass(frozen=True, slots=True)
class OnlyRiskPipelineResult:
    decision: OnlyRiskDecision
    rule_order: tuple[OnlyRiskRuleId, ...]


class OnlyRiskPipeline:
    def __init__(self, rules: tuple[OnlyRiskRule, ...], config: OnlyRiskPipelineConfig | None = None) -> None:
        self.config = config or OnlyRiskPipelineConfig()
        ordered = sorted(
            rules, key=lambda rule: (_ONLY_SCOPE_ORDER[rule.scope], rule.metadata.order, str(rule.rule_id))
        )
        ids = tuple(rule.rule_id for rule in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("Risk Pipeline contains duplicate RuleId")
        self._rules = tuple(ordered)

    @property
    def rules(self) -> tuple[OnlyRiskRule, ...]:
        return self._rules

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskPipelineResult:
        evaluated: list[OnlyRiskRuleId] = []
        observations: list[OnlyRiskObservation] = []
        rule_order = tuple(rule.rule_id for rule in self._rules)
        for rule in self._rules:
            evaluated.append(rule.rule_id)
            try:
                decision = rule.evaluate(request, context)
                if not isinstance(decision, OnlyRiskDecision):
                    raise TypeError("Risk Rule must return OnlyRiskDecision")
            except Exception as exc:
                error = OnlyRiskErrorInfo(
                    rule.rule_id,
                    rule.scope,
                    type(exc).__name__,
                    str(exc),
                    context.runtime_id,
                    context.cluster_id,
                    context.account_id,
                    request.request_id,
                    context.ts_event,
                    context.ts_init,
                )
                return OnlyRiskPipelineResult(
                    OnlyRiskDecision.failed(error, tuple(evaluated), tuple(observations)),
                    rule_order,
                )
            if decision.is_error:
                decision_error = decision.error
                if decision_error is None:
                    raise AssertionError("ERROR Risk Decision lost error detail")
                return OnlyRiskPipelineResult(
                    OnlyRiskDecision.failed(decision_error, tuple(evaluated), tuple(observations)),
                    rule_order,
                )
            if decision.is_rejected:
                rejection = decision.rejection
                if rejection is None:
                    raise AssertionError("REJECT Risk Decision lost rejection detail")
                if rule.mode is OnlyRiskRuleMode.OBSERVING:
                    observations.append(
                        OnlyRiskObservation(
                            rejection.rule_id,
                            rejection.code,
                            rejection.message,
                            rejection.scope,
                            rejection.details,
                        )
                    )
                    continue
                return OnlyRiskPipelineResult(
                    OnlyRiskDecision.rejected(rejection, tuple(evaluated), tuple(observations)),
                    rule_order,
                )
        return OnlyRiskPipelineResult(
            OnlyRiskDecision.accepted(tuple(evaluated), tuple(observations)),
            rule_order,
        )
