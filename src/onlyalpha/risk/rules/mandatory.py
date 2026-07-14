"""Non-removable System Risk Rules."""

from onlyalpha.domain.enums import OnlyOrderType, OnlySecurityStatus
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


class OnlyInstrumentTradingStatusRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.instrument_tradable", 40))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None:
            return self._accept()
        if instrument.status is not OnlySecurityStatus.ACTIVE or not instrument.is_effective_at(
            context.ts_event.to_datetime()
        ):
            return self._reject(
                OnlyRiskRejectionCode.INSTRUMENT_NOT_TRADABLE,
                "Instrument is not active at the Risk evaluation time",
                requested_value=instrument.status.value,
                allowed_value=OnlySecurityStatus.ACTIVE.value,
            )
        return self._accept()


class OnlyOrderTypeSupportedRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.order_type_supported", 50))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        if request.order_type not in context.supported_order_types:
            return self._reject(
                OnlyRiskRejectionCode.UNSUPPORTED_ORDER_TYPE,
                "Execution Port does not support this Order type",
                requested_value=request.order_type.value,
                allowed_value=",".join(sorted(item.value for item in context.supported_order_types)),
            )
        return self._accept()


class OnlyBasicPriceRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.basic_price", 60))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del context
        if request.order_type is OnlyOrderType.LIMIT and (request.price is None or request.price.value <= 0):
            return self._reject(OnlyRiskRejectionCode.INVALID_PRICE, "LIMIT requires a positive Price")
        if request.order_type is OnlyOrderType.MARKET and request.price is not None:
            return self._reject(OnlyRiskRejectionCode.INVALID_PRICE, "MARKET cannot carry a Price")
        return self._accept()


class OnlyBasicQuantityRiskRule(OnlyRiskRule):
    def __init__(self) -> None:
        super().__init__(_mandatory("system.basic_quantity", 70))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del context
        if request.quantity.value <= 0:
            return self._reject(OnlyRiskRejectionCode.INVALID_QUANTITY, "Order quantity must be positive")
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
        OnlyInstrumentTradingStatusRiskRule(),
        OnlyOrderTypeSupportedRiskRule(),
        OnlyBasicPriceRiskRule(),
        OnlyBasicQuantityRiskRule(),
        OnlyKillSwitchRiskRule(),
    )


ONLY_MANDATORY_RISK_RULE_IDS = frozenset(rule.rule_id for rule in only_mandatory_rules(OnlyRuntimeId("template")))
