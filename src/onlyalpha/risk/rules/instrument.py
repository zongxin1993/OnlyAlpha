"""Instrument and MarketRule driven checks without market-specific branches."""

from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision
from onlyalpha.risk.enums import OnlyRiskRejectionCode, OnlyRiskRuleScope
from onlyalpha.risk.identifiers import OnlyRiskRuleId
from onlyalpha.risk.rules.base import OnlyRiskRule, OnlyRiskRuleMetadata


def _instrument_rule(rule_id: str, order: int) -> OnlyRiskRuleMetadata:
    return OnlyRiskRuleMetadata(OnlyRiskRuleId(rule_id), OnlyRiskRuleScope.INSTRUMENT, order=order)


class OnlyPriceIncrementRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 100) -> None:
        super().__init__(_instrument_rule("instrument.price_increment", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None or request.price is None:
            return self._accept()
        valid = (
            request.price.precision == instrument.price_precision
            and request.price.value % instrument.tick_size.value == 0
        )
        if not valid:
            return self._reject(
                OnlyRiskRejectionCode.INVALID_PRICE_INCREMENT,
                "Price does not match Instrument or MarketRule increment",
                requested_value=str(request.price.value),
                allowed_value=str(instrument.tick_size.value),
            )
        return self._accept()


class OnlyQuantityIncrementRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 110) -> None:
        super().__init__(_instrument_rule("instrument.quantity_increment", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None:
            return self._accept()
        valid = (
            request.quantity.precision == instrument.quantity_precision
            and request.quantity.value % instrument.step_size.value == 0
        )
        if not valid:
            return self._reject(
                OnlyRiskRejectionCode.INVALID_QUANTITY_INCREMENT,
                "Quantity does not match Instrument or MarketRule increment",
                requested_value=str(request.quantity.value),
                allowed_value=str(instrument.step_size.value),
            )
        return self._accept()


class OnlyMinimumQuantityRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 120) -> None:
        super().__init__(_instrument_rule("instrument.minimum_quantity", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        minimum = None if instrument is None else instrument.minimum_quantity
        if minimum is not None and request.quantity.value < minimum.value:
            return self._reject(
                OnlyRiskRejectionCode.MINIMUM_QUANTITY_NOT_MET,
                "Order quantity is below Instrument minimum",
                requested_value=str(request.quantity.value),
                allowed_value=str(minimum.value),
            )
        return self._accept()


class OnlyMaximumQuantityRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 130) -> None:
        super().__init__(_instrument_rule("instrument.maximum_quantity", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        maximum = None if instrument is None else instrument.maximum_quantity
        if maximum is not None and request.quantity.value > maximum.value:
            return self._reject(
                OnlyRiskRejectionCode.MAXIMUM_QUANTITY_EXCEEDED,
                "Order quantity exceeds Instrument maximum",
                requested_value=str(request.quantity.value),
                allowed_value=str(maximum.value),
            )
        return self._accept()


class OnlyMinimumNotionalRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 140) -> None:
        super().__init__(_instrument_rule("instrument.minimum_notional", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        instrument = context.instruments.get(request.instrument_id)
        if instrument is None:
            return self._accept()
        minimum = instrument.minimum_notional
        if minimum is None:
            return self._accept()
        price = request.price
        if price is None and context.market_data is not None:
            price = context.market_data.primary_bar.close
        if price is None:
            return self._reject(
                OnlyRiskRejectionCode.REQUIRED_RISK_DATA_MISSING,
                "Price is required to validate minimum notional",
            )
        notional = price.value * request.quantity.value * instrument.contract_multiplier.value
        if notional < minimum.amount:
            return self._reject(
                OnlyRiskRejectionCode.MINIMUM_NOTIONAL_NOT_MET,
                "Order notional is below minimum",
                requested_value=str(notional),
                allowed_value=str(minimum.amount),
            )
        return self._accept()


class OnlyTradingSessionRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 150) -> None:
        super().__init__(_instrument_rule("instrument.trading_session", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        calendar = context.trading_calendar
        if not calendar.is_trading_time(context.ts_event) and not self._is_closed_bar_decision(request, context):
            return self._reject(
                OnlyRiskRejectionCode.OUTSIDE_TRADING_SESSION,
                "Order is outside the configured TradingCalendar session",
            )
        return self._accept()

    @staticmethod
    def _is_closed_bar_decision(
        request: OnlyOrderRequest,
        context: OnlyRiskEvaluationContext,
    ) -> bool:
        """Allow a strategy decision at an observed closed Bar boundary.

        Trading sessions are half-open, so a daily Bar stamped exactly at the
        session close is not itself trading time.  The immutable snapshot ties
        this exception to the same instrument and event timestamp; arbitrary
        after-hours commands remain rejected.
        """

        snapshot = context.market_data
        return (
            snapshot is not None
            and snapshot.instrument_id == request.instrument_id
            and snapshot.ts_event == context.ts_event
            and snapshot.primary_bar.is_closed
            and snapshot.primary_bar.instrument_id == request.instrument_id
            and snapshot.primary_bar.ts_event == context.ts_event.to_datetime()
        )


class OnlyPriceLimitRiskRule(OnlyRiskRule):
    def __init__(self, *, order: int = 160) -> None:
        super().__init__(_instrument_rule("instrument.price_limit", order))

    def evaluate(self, request: OnlyOrderRequest, context: OnlyRiskEvaluationContext) -> OnlyRiskDecision:
        if request.price is None:
            return self._accept()
        instrument = context.instruments.get(request.instrument_id)
        valid = instrument is None or (
            (instrument.minimum_price is None or request.price.value >= instrument.minimum_price.value)
            and (instrument.maximum_price is None or request.price.value <= instrument.maximum_price.value)
        )
        if not valid:
            return self._reject(
                OnlyRiskRejectionCode.PRICE_LIMIT_EXCEEDED,
                "Price exceeds configured Instrument limit",
                requested_value=str(request.price.value),
            )
        return self._accept()


def only_default_instrument_rules() -> tuple[OnlyRiskRule, ...]:
    return (
        OnlyPriceIncrementRiskRule(),
        OnlyQuantityIncrementRiskRule(),
        OnlyMinimumQuantityRiskRule(),
        OnlyMaximumQuantityRiskRule(),
        OnlyMinimumNotionalRiskRule(),
        OnlyTradingSessionRiskRule(),
        OnlyPriceLimitRiskRule(),
    )
