"""Closed, pure Backtest plugin transitions. Never dispatches to a real venue."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig
from onlyalpha_plugin_broker_virtual.gateway import OnlyVirtualBrokerGateway

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import OnlyBrokerOrderRequest
from onlyalpha.broker.updates import (
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha_calculation_worker.contracts import decode, encode, exact, integer, scalar


def _configuration(value: object) -> tuple[dict[str, Any], OnlyVirtualBrokerConfig]:
    c = exact(value, {"schema_version", "execution", "instrument", "maximum_fill_quantity", "requests", "calendar"})
    if c["schema_version"] != 1 or c["execution"]["runtime_kind"] != "BACKTEST":
        raise ValueError("BACKTEST_ONLY")
    e = c["execution"]
    instrument = OnlyInstrument.from_dict(c["instrument"])
    currency = OnlyCurrency.from_dict(e["currency"])
    if instrument.settlement_currency != currency or instrument.contract_multiplier.value != Decimal(1):
        raise ValueError("BACKTEST_CASH_CONFIGURATION")
    maximum = (
        None
        if c["maximum_fill_quantity"] is None
        else OnlyQuantity(Decimal(c["maximum_fill_quantity"]), instrument.quantity_precision)
    )
    if maximum is not None:
        scalar(maximum.value)
    requests = c["requests"]
    if type(requests) is not list or len(requests) > 16:
        raise ValueError("BACKTEST_POLICY_BOUND")
    # Reserve the complete declared simulated fill history before any external candidate exists.
    slots = 0
    for record in requests:
        from onlyalpha.domain.execution import OnlyOrderRequest

        request = OnlyOrderRequest.from_dict(record)
        if (
            request.instrument_id != instrument.instrument_id
            or request.quantity.precision != instrument.quantity_precision
        ):
            raise ValueError("BACKTEST_POLICY_INSTRUMENT")
        scalar(request.quantity.value)
        if maximum is None:
            slots += 1
        else:
            ratio = Fraction(request.quantity.value) / Fraction(maximum.value)
            slots += (ratio.numerator + ratio.denominator - 1) // ratio.denominator
    if slots > 64:
        raise ValueError("BACKTEST_FILL_HISTORY_BOUND")
    return c, OnlyVirtualBrokerConfig(
        OnlyBrokerGatewayId(e["gateway"]),
        OnlyAccountId(e["account"]),
        currency,
        OnlyMoney(Decimal(e["initial_cash"]), currency),
        maximum_fill_quantity=maximum,
    )


def dispatch(value: object) -> dict[str, Any]:
    r = exact(value, {"schema_version", "configuration", "checkpoint", "operation", "payload", "now"})
    if r["schema_version"] != 1:
        raise ValueError("BACKTEST_PROTOCOL")
    c, config = _configuration(r["configuration"])
    operation = r["operation"]
    if operation not in {"INIT", "VALIDATE", "BAR", "SUBMIT", "ADMISSION", "FEE"}:
        raise ValueError("BACKTEST_OPERATION")
    now = OnlyTimestamp.from_unix_nanos(integer(r["now"]))
    if now.unix_nanos % 1000:
        raise ValueError("BACKTEST_PLUGIN_TIME_PRECISION")
    if operation in {"ADMISSION", "FEE"}:
        from onlyalpha_calculation_worker.backtest_policy import policy

        return policy(c, operation, r["payload"], now)
    if now.unix_nanos % 1000:
        raise ValueError("BACKTEST_PLUGIN_TIME_PRECISION")
    clock = OnlyBacktestClock(now.to_datetime())
    updates: list[Any] = []
    gateway = OnlyVirtualBrokerGateway(config, OnlyRuntimeId(c["execution"]["runtime"]), clock, updates.append)
    if operation == "INIT":
        if r["checkpoint"] is not None or r["payload"] != {}:
            raise ValueError("BACKTEST_INIT")
        gateway.connect()
        gateway.authenticate()
        updates.clear()
    else:
        if r["checkpoint"] is None:
            raise ValueError("BACKTEST_CHECKPOINT_REQUIRED")
        gateway.restore_checkpoint(r["checkpoint"])
        if encode(gateway.capture_checkpoint()) != encode(r["checkpoint"]):
            raise ValueError("BACKTEST_CHECKPOINT_CANONICAL")
        payload = r["payload"]
        if operation == "BAR":
            exact(payload, {"bar"})
            bar = OnlyBar.from_dict(payload["bar"])
            if OnlyTimestamp.from_datetime(bar.ts_event) != now:
                raise ValueError("BACKTEST_CLOCK_RELATION")
            gateway.on_bar(bar)
            gateway.run_due()
        elif operation == "SUBMIT":
            exact(payload, {"request"})
            request = OnlyBrokerOrderRequest.from_dict(payload["request"])
            if request.account_id != config.account_id or request.submitted_at != now:
                raise ValueError("BACKTEST_SUBMIT_CONTEXT")
            submission = gateway.submit_order(request)
            if not submission.request_received:
                raise ValueError("BACKTEST_SUBMIT_DENIED")
            gateway.run_due()
        elif payload != {}:
            raise ValueError("BACKTEST_VALIDATION_FIELDS")
    day = None
    if operation in {"BAR", "SUBMIT"}:
        from onlyalpha.domain.calendar import OnlyTradingCalendar

        day = OnlyTradingCalendar.from_dict(c["calendar"]).trading_day_at(now)
        if operation == "BAR" and str(day.value) != str(bar.trading_day):
            raise ValueError("BACKTEST_TRADING_DAY_RELATION")
    kinds = {
        OnlyBrokerOrderAcceptedUpdate: "ACCEPT",
        OnlyBrokerTradeUpdate: "FILL",
        OnlyBrokerOrderCancelledUpdate: "CANCELLED",
        OnlyBrokerOrderRejectedUpdate: "REJECTED",
        OnlyBrokerOrderExpiredUpdate: "EXPIRED",
    }
    normalized = []
    for update in updates:
        if type(update) not in kinds:
            raise ValueError("BACKTEST_UNSUPPORTED_BROKER_FACT")
        normalized.append({"kind": kinds[type(update)], "update": update.to_dict()})
    result = {
        "schema_version": 1,
        "checkpoint": gateway.capture_checkpoint(),
        "updates": normalized,
        "open_orders": [order.to_dict() for order in gateway.query_open_orders(config.account_id)],
        "pending": len(gateway.scheduler),
        "trading_day": None if day is None else str(day.value),
        "day_index": None if day is None else day.value.toordinal(),
    }
    return exact(decode(encode(result)), set(result))
