"""Translate actual Market Product and Fee owners into the native comparison port."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from onlyalpha_plugin_broker_virtual.fee_contract import fee_contract
from onlyalpha_plugin_generic_t0_cash.factory import OnlyGenericT0CashMarketProductFactory

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.numeric import only_add, only_multiply
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.trading import OnlyPositionEffect
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.accrual import OnlyOrderFeeAccrualAuthority, OnlyOrderFeeAccrualState
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.engine import OnlyFeeEngine
from onlyalpha.fee.resolver import OnlyFeeResolver
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
)
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine, OnlyPreTradeMarketContext
from onlyalpha_calculation_worker.contracts import exact


class _NoExternalResources:
    def require_reference_authority(self, resource_id: str) -> Any:
        raise ValueError("BACKTEST_EXTERNAL_MARKET_RESOURCE_UNSUPPORTED")

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> Any:
        raise ValueError("BACKTEST_EXTERNAL_MARKET_RESOURCE_UNSUPPORTED")


def policy(configuration: dict[str, Any], operation: str, payload: object, now: OnlyTimestamp) -> dict[str, Any]:
    instrument = OnlyInstrument.from_dict(configuration["instrument"])
    calendar = OnlyTradingCalendar.from_dict(configuration["calendar"])
    day = calendar.trading_day_at(now)
    binding = OnlyGenericT0CashMarketProductFactory().resolve(
        OnlyMarketProductConfig(
            OnlyMarketProductPluginId("onlyalpha-plugin-generic-t0-cash"),
            OnlyMarketProductId("GENERIC_T0_CASH"),
            OnlyMarketProductVersion("1"),
            OnlyCanonicalMarketProductConfig(),
        ),
        OnlyMarketProductResolutionContext(_NoExternalResources(), (instrument,)),
    )
    rules = OnlyMarketRuleEngine(
        binding=binding, advance_trading_day=lambda d, lag: OnlyTradingDay(date.fromordinal(d.value.toordinal() + lag))
    )
    fees = OnlyFeeResolver(
        OnlyFeeEngine(),
        binding.market_fee_pack,
        fee_contract(),
        "virtual",
        rules,
        {instrument.instrument_id: instrument},
        only_default_fee_basis_provider_registry(),
        calendar.trading_day_at,
    )
    r = exact(payload, {"order", "state"} if operation == "ADMISSION" else {"order", "fill", "accrual"})
    order = OnlyOrderSnapshot.from_dict(r["order"])
    e = configuration["execution"]
    if (
        str(order.runtime_id) != e["runtime"]
        or str(order.account_id) != e["account"]
        or order.instrument_id != instrument.instrument_id
    ):
        raise ValueError("BACKTEST_POLICY_SCOPE")
    if order.price is None or order.execution_intent is None:
        raise ValueError("BACKTEST_ORDER_PROOF_REQUIRED")
    if operation == "ADMISSION":
        state = r["state"]
        available = next(
            (
                Decimal(row["snapshot"]["available"])
                for row in state["position"]["allocations"]
                if row["cluster"] == str(order.cluster_id) and row["instrument"] == str(order.instrument_id)
            ),
            Decimal(0),
        )
        decision = rules.evaluate_pre_trade(
            OnlyPreTradeMarketContext(
                str(order.instrument_id),
                order.side,
                order.quantity.value,
                order.price.value,
                now.to_datetime(),
                day,
                unreserved_sellable_quantity=available,
                trade_available_cash=Decimal(state["account"]["snapshot"]["trade_available"]),
                position_effect=OnlyPositionEffect(order.execution_intent.position_effect.value),
                order_type=order.order_type,
                time_in_force=order.time_in_force,
            )
        )
        if not decision.accepted:
            return {"schema_version": 1, "accepted": False, "reason": decision.reason_code}
        fee_binding = fees.bind_order(order, now)
        estimate = fees.estimate_order(order, fee_binding, order.price, now, maximum_fill_count=64)
        funding = fees.funding_plan(order, fee_binding, estimate, order.price)
        notional = OnlyMoney(only_multiply(order.price.value, order.quantity.value), instrument.settlement_currency)
        return {
            "schema_version": 1,
            "accepted": True,
            "contract": {
                "binding": fee_binding.to_dict(),
                "estimate": estimate.to_dict(),
                "funding": funding.to_dict(),
            },
            "fee_budget": str(estimate.reservation_charge.amount),
            "notional": notional.to_dict(),
            "market_policy": binding.composition_identity.fingerprint,
        }
    if order.fee_policy_binding is None:
        raise ValueError("BACKTEST_FEE_BINDING_REQUIRED")
    fill = OnlyOrderFill.from_dict(r["fill"])
    if fill.order_id != order.order_id or fill.ts_event != now:
        raise ValueError("BACKTEST_FILL_RELATION")
    before = None if r["accrual"] is None else OnlyOrderFeeAccrualState.from_dict(r["accrual"])
    quantity = only_add(order.filled_quantity.value, fill.quantity.value)
    previous_notional = Decimal(0) if before is None else before.cumulative_fill_notional.amount
    notional = OnlyMoney(
        only_add(previous_notional, only_multiply(fill.price.value, fill.quantity.value)),
        instrument.settlement_currency,
    )
    assessment = fees.assess_trade(
        order,
        order.fee_policy_binding,
        trade_id=fill.trade_id,
        price=fill.price,
        quantity=fill.quantity.value,
        timestamp=now,
        liquidity_role=fill.liquidity_side,
        cumulative_quantity=quantity,
        cumulative_notional=notional,
    )
    after, application = OnlyOrderFeeAccrualAuthority().apply(
        before,
        assessment,
        cumulative_fill_quantity=type(fill.quantity)(quantity, fill.quantity.precision),
        cumulative_fill_notional=notional,
        updated_at=now,
        order_fixed_policy_fingerprint=order.fee_policy_binding.fingerprint,
    )
    gross = OnlyMoney(only_multiply(fill.price.value, fill.quantity.value), instrument.settlement_currency)
    compiled = rules.compiled_rules(str(instrument.instrument_id), day, as_of=now.to_datetime())
    settlement = compiled.settlement_policy.compile()
    settlement_policy = {
        "id": settlement.policy_id,
        "version": compiled.identity.policy_fingerprint,
        "asset_booked": settlement.asset_booking_lag,
        "asset_trade_available": settlement.asset_trade_availability_lag,
        "cash_booked": settlement.cash_booking_lag,
        "cash_trade_available": settlement.cash_trade_availability_lag,
        "cash_withdrawable": settlement.cash_withdrawal_lag,
        "legal_settled": settlement.legal_settlement_lag,
    }

    return {
        "schema_version": 1,
        "accrual": after.to_dict(),
        "charge_target": str(after.cumulative_charges.amount),
        "rebate_target": str(after.cumulative_rebates.amount),
        "gross_notional": gross.to_dict(),
        "application": application.to_dict(),
        "settlement_policy": settlement_policy,
    }
