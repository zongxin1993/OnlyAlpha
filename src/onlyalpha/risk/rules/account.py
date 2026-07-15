"""Account/Position dependent Rules which fail closed when their Ports are unavailable."""

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskErrorInfo
from onlyalpha.risk.enums import OnlyRiskRejectionCode, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


class OnlyAvailableBalanceRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 100) -> None:
        super().__init__(
            OnlyRiskRuleMetadata(OnlyRiskRuleId("account.available_balance"), OnlyRiskRuleScope.ACCOUNT, order=order)
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        snapshot = context.account_risk.snapshot(context.account_id)
        if not context.account_risk.available or snapshot is None:
            return OnlyRiskDecision.failed(
                OnlyRiskErrorInfo(
                    self.rule_id,
                    self.scope,
                    "OnlyRiskDataUnavailableError",
                    "Account Risk Snapshot is unavailable",
                    context.runtime_id,
                    context.cluster_id,
                    context.account_id,
                    request.request_id,
                    context.ts_event,
                    context.ts_init,
                )
            )
        reference_price = (
            request.price
            if request.price is not None
            else context.market_data.primary_bar.close
            if context.market_data is not None
            else None
        )
        if reference_price is None:
            return OnlyRiskDecision.failed(
                OnlyRiskErrorInfo(
                    self.rule_id,
                    self.scope,
                    "OnlyRiskDataUnavailableError",
                    "Price is required for balance Risk",
                    context.runtime_id,
                    context.cluster_id,
                    context.account_id,
                    request.request_id,
                    context.ts_event,
                    context.ts_init,
                )
            )
        if not snapshot.allows_new_orders:
            return self._reject(
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED,
                f"Account status blocks new orders: {snapshot.status}",
            )
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None:
            return self._reject(
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED,
                "Account balance check requires a known Instrument",
            )
        balance = next(
            (item for item in snapshot.available_balances if item.currency == instrument.settlement_currency),
            None,
        )
        if balance is None:
            return self._reject(
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED,
                "Account has no available balance in the order currency",
            )
        required = reference_price.value * request.quantity.value
        if request.side is OnlyOrderSide.BUY and required > balance.amount:
            return self._reject(
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED,
                "order notional exceeds Account available cash",
                requested_value=str(required),
                allowed_value=str(balance.amount),
            )
        return self._accept()


class OnlyAvailablePositionRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 100) -> None:
        super().__init__(
            OnlyRiskRuleMetadata(OnlyRiskRuleId("account.available_position"), OnlyRiskRuleScope.ACCOUNT, order=order)
        )

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        if request.side is OnlyOrderSide.BUY:
            return self._accept()
        snapshot = context.position_risk.snapshot(context.account_id, request.instrument_id)
        if not context.position_risk.available or snapshot is None:
            return OnlyRiskDecision.failed(
                OnlyRiskErrorInfo(
                    self.rule_id,
                    self.scope,
                    "OnlyRiskDataUnavailableError",
                    "Position Risk Snapshot is unavailable",
                    context.runtime_id,
                    context.cluster_id,
                    context.account_id,
                    request.request_id,
                    context.ts_event,
                    context.ts_init,
                )
            )
        cluster_snapshot = context.position_risk.cluster_snapshot(
            context.account_id,
            context.cluster_id,
            request.instrument_id,
        )
        if cluster_snapshot is None:
            return OnlyRiskDecision.failed(
                OnlyRiskErrorInfo(
                    self.rule_id,
                    self.scope,
                    "OnlyRiskDataUnavailableError",
                    "Cluster Position Allocation Snapshot is unavailable",
                    context.runtime_id,
                    context.cluster_id,
                    context.account_id,
                    request.request_id,
                    context.ts_event,
                    context.ts_init,
                )
            )
        if request.quantity.value > min(
            snapshot.available_quantity.value,
            cluster_snapshot.available_quantity.value,
        ):
            return self._reject(
                OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED,
                "sell exceeds account or Cluster available Position",
                requested_value=str(request.quantity.value),
                allowed_value=str(min(snapshot.available_quantity.value, cluster_snapshot.available_quantity.value)),
            )
        return self._accept()
