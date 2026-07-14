"""Runtime and Cluster profile Risk Rules."""

from decimal import Decimal

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import OnlyRiskRejectionCode, OnlyRiskRuleMode, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


def _metadata(
    rule_id: str,
    scope: OnlyRiskRuleScope,
    order: int,
    mode: OnlyRiskRuleMode,
) -> OnlyRiskRuleMetadata:
    return OnlyRiskRuleMetadata(OnlyRiskRuleId(rule_id), scope, mode, order)


class OnlyMaxActiveOrdersRiskRule(OnlyRiskRule):
    def __init__(self, maximum: int, *, order: int = 100, mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING) -> None:
        if maximum < 0:
            raise ValueError("maximum active orders cannot be negative")
        super().__init__(_metadata("runtime.max_active_orders", OnlyRiskRuleScope.RUNTIME, order, mode))
        self.maximum = maximum

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        current = context.orders.active_count()
        if current >= self.maximum:
            return self._reject(
                OnlyRiskRejectionCode.MAX_ACTIVE_ORDERS_EXCEEDED,
                "Runtime active Order limit reached",
                requested_value=str(current + 1),
                allowed_value=str(self.maximum),
            )
        return self._accept()


class OnlyMaxClusterActiveOrdersRiskRule(OnlyRiskRule):
    def __init__(self, maximum: int, *, order: int = 100, mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING) -> None:
        if maximum < 0:
            raise ValueError("maximum Cluster active orders cannot be negative")
        super().__init__(_metadata("cluster.max_active_orders", OnlyRiskRuleScope.CLUSTER, order, mode))
        self.maximum = maximum

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        current = context.orders.active_count(cluster_id=context.cluster_id)
        if current >= self.maximum:
            return self._reject(
                OnlyRiskRejectionCode.MAX_CLUSTER_ACTIVE_ORDERS_EXCEEDED,
                "Cluster active Order limit reached",
                requested_value=str(current + 1),
                allowed_value=str(self.maximum),
            )
        return self._accept()


class OnlyMaxInstrumentActiveOrdersRiskRule(OnlyRiskRule):
    def __init__(self, maximum: int, *, order: int = 100, mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING) -> None:
        if maximum < 0:
            raise ValueError("maximum Instrument active orders cannot be negative")
        super().__init__(_metadata("runtime.max_instrument_active_orders", OnlyRiskRuleScope.RUNTIME, order, mode))
        self.maximum = maximum

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        current = context.orders.active_count(instrument_id=request.instrument_id)
        if current >= self.maximum:
            return self._reject(
                OnlyRiskRejectionCode.MAX_INSTRUMENT_ACTIVE_ORDERS_EXCEEDED,
                "Instrument active Order limit reached",
                requested_value=str(current + 1),
                allowed_value=str(self.maximum),
            )
        return self._accept()


class OnlyMaxOrderQuantityRiskRule(OnlyRiskRule):
    def __init__(
        self,
        maximum: OnlyQuantity,
        *,
        order: int = 100,
        mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING,
    ) -> None:
        super().__init__(_metadata("cluster.max_order_quantity", OnlyRiskRuleScope.CLUSTER, order, mode))
        self.maximum = maximum

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del context
        if request.quantity.value > self.maximum.value:
            return self._reject(
                OnlyRiskRejectionCode.MAXIMUM_QUANTITY_EXCEEDED,
                "Order quantity exceeds Profile maximum",
                requested_value=str(request.quantity.value),
                allowed_value=str(self.maximum.value),
            )
        return self._accept()


class OnlyMaxOrderNotionalRiskRule(OnlyRiskRule):
    def __init__(
        self,
        maximum: OnlyMoney,
        *,
        include_active_reservations: bool = True,
        order: int = 100,
        mode: OnlyRiskRuleMode = OnlyRiskRuleMode.ENFORCING,
    ) -> None:
        super().__init__(_metadata("cluster.max_order_notional", OnlyRiskRuleScope.CLUSTER, order, mode))
        self.maximum = maximum
        self.include_active_reservations = include_active_reservations

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None:
            return self._accept()
        if instrument.quote_currency != self.maximum.currency:
            return self._reject(
                OnlyRiskRejectionCode.REQUIRED_RISK_DATA_MISSING,
                "Profile notional currency does not match Instrument quote currency",
                requested_value=instrument.quote_currency.code,
                allowed_value=self.maximum.currency.code,
            )
        if request.price is None:
            return self._reject(
                OnlyRiskRejectionCode.REQUIRED_RISK_DATA_MISSING,
                "A reliable Price is required for notional Risk",
            )
        requested = request.price.value * request.quantity.value * instrument.contract_multiplier.value
        reserved = Decimal("0")
        if self.include_active_reservations:
            reserved = context.reservations.active_notional(
                self.maximum.currency,
                cluster_id=context.cluster_id,
            ).amount
        total = requested + reserved
        if total > self.maximum.amount:
            code = (
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED
                if reserved > 0
                else OnlyRiskRejectionCode.MAXIMUM_ORDER_NOTIONAL_EXCEEDED
            )
            return self._reject(
                code,
                "Order plus active reservations exceed Profile notional limit",
                requested_value=str(total),
                allowed_value=str(self.maximum.amount),
                details={"order_notional": str(requested), "reserved_notional": str(reserved)},
            )
        return self._accept()


class OnlyClusterInstrumentPermissionRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 100) -> None:
        super().__init__(
            _metadata("cluster.instrument_permission", OnlyRiskRuleScope.CLUSTER, order, OnlyRiskRuleMode.ENFORCING)
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        if not context.permissions.instrument_is_authorized(context.cluster_id, request.instrument_id):
            return self._reject(
                OnlyRiskRejectionCode.CLUSTER_NOT_AUTHORIZED,
                "Cluster is not authorized for Instrument",
                requested_value=str(request.instrument_id),
            )
        return self._accept()


class OnlyClusterAccountPermissionRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 110) -> None:
        super().__init__(
            _metadata("cluster.account_permission", OnlyRiskRuleScope.CLUSTER, order, OnlyRiskRuleMode.ENFORCING)
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        del request
        if not context.permissions.account_is_authorized(context.cluster_id, context.account_id):
            return self._reject(
                OnlyRiskRejectionCode.ACCOUNT_NOT_AUTHORIZED,
                "Cluster is not authorized for Account",
                requested_value=str(context.account_id),
            )
        return self._accept()
