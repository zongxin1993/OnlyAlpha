"""Non-removable System Risk Rules."""

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import OnlyRiskRejectionCode, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


def _mandatory(rule_id: str, order: int) -> OnlyRiskRuleMetadata:
    return OnlyRiskRuleMetadata(
        OnlyRiskRuleId(rule_id),
        OnlyRiskRuleScope.SYSTEM,
        order=order,
        mandatory=True,
    )


class OnlyRuntimeScopeRiskRule(OnlyRiskRule):
    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        super().__init__(_mandatory("system.runtime_scope", 10))
        self._runtime_id = runtime_id

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        if context.runtime_id != self._runtime_id:
            return self._reject(OnlyRiskRejectionCode.CLUSTER_NOT_AUTHORIZED, "Runtime Scope mismatch")
        return self._accept()


class OnlyClusterScopeRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.cluster_scope", 20))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        if not context.profile_bound or not context.permissions.cluster_is_authorized(context.cluster_id):
            return self._reject(OnlyRiskRejectionCode.CLUSTER_NOT_AUTHORIZED, "Cluster has no bound Risk Profile")
        return self._accept()


class OnlyInstrumentExistsRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.instrument_exists", 30))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        if context.instruments.get(request.instrument_id) is None:
            return self._reject(
                OnlyRiskRejectionCode.INSTRUMENT_NOT_FOUND,
                "Instrument is not registered in this Runtime",
                requested_value=str(request.instrument_id),
            )
        return self._accept()


class OnlyKillSwitchRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.kill_switch", 80))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        if context.kill_switch_active:
            return self._reject(
                OnlyRiskRejectionCode.KILL_SWITCH_ACTIVE,
                "An applicable mandatory Kill Switch is active",
            )
        return self._accept()


def only_mandatory_rules(runtime_id: OnlyRuntimeId) -> tuple[OnlyRiskRule, ...]:
    return (
        OnlyRuntimeScopeRiskRule(runtime_id),
        OnlyClusterScopeRiskRule(),
        OnlyInstrumentExistsRiskRule(),
        OnlyKillSwitchRiskRule(),
    )


ONLY_MANDATORY_RISK_RULE_IDS = frozenset(rule.rule_id for rule in only_mandatory_rules(OnlyRuntimeId("template")))
