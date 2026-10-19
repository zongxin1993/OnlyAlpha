"""Actual AccountManager and pure reducers vs independent literal cash vectors."""

from __future__ import annotations

# ruff: noqa: E402
import json
import sys
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onlyalpha.account.enums import OnlyAccountReservationState, OnlyAccountStatus, OnlyAccountType
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountConfig, OnlyAccountTradeCashFlow
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.fee import (
    OnlyFeeAuthority,
    OnlyFeeCalculationScope,
    OnlyFeeComponentIdentity,
    OnlyFeeEconomicDirection,
    OnlyFeeResolutionPolicy,
    OnlyFeeSubject,
    OnlyFeeType,
    OnlyLocalFeeFinality,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.execution.execution_state import OnlyAccountCashReservationExecutionState, OnlyAccountExecutionState
from onlyalpha.execution.planned_trade import OnlyPlannedTrade
from onlyalpha.execution.reducers.trade_accounting import OnlyAccountTradeReducer
from onlyalpha.execution.reducers.trade_reservations import OnlyAccountCashReservationTradeReducer
from onlyalpha.fee.application import OnlyFeeApplicationComponent, OnlyFeeApplicationInstruction
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide, OnlySettlementBucket


def reference_outputs() -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    currency = OnlyCurrency("USD", 2)
    runtime, account_id, order = OnlyRuntimeId("runtime"), OnlyAccountId("account"), OnlyOrderId("order")
    cluster, instrument = OnlyClusterId("cluster"), OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    subject = OnlyFeeSubject(runtime, account_id, cluster, order, instrument)

    def money(s: str | Decimal) -> OnlyMoney:
        return OnlyMoney(Decimal(s), currency)

    with localcontext() as decimal_context:
        decimal_context.prec = 128
        zero, instant = money("0.00"), OnlyTimestamp(0)
        for line in (ROOT / "test-data/account/cash-v1.jsonl").read_text().splitlines():
            case = json.loads(line)
            initial, reserved = money(case["initial"]), money(case["reserve"])
            account = OnlyAccountExecutionState(
                runtime,
                account_id,
                "gateway",
                OnlyAccountType.CASH,
                currency,
                OnlyAccountStatus.ACTIVE,
                initial,
                initial - reserved,
                initial - reserved,
                reserved,
                zero,
                zero,
                zero,
                zero,
                zero,
                initial,
                instant,
                instant,
                None,
                1,
                None,
                (),
                None,
                None,
                None,
                None,
            )
            reservation = OnlyAccountCashReservationExecutionState(
                "reservation",
                runtime,
                account_id,
                order,
                reserved,
                zero,
                reserved,
                OnlyAccountReservationState.ACTIVE,
                instant,
                instant,
                1,
            )
            native = OnlyAccountManager(runtime)
            native.create_account(
                OnlyAccountConfig(runtime, account_id, "gateway", OnlyAccountType.CASH, currency, initial), instant
            )
            observed: list[list[str]] = []
            for n, (side, notional, charges, rebates, realized, terminal) in enumerate(case["fills"], 1):
                components = []
                for direction, amount in (
                    (OnlyFeeEconomicDirection.CHARGE, charges),
                    (OnlyFeeEconomicDirection.REBATE, rebates),
                ):
                    if Decimal(amount):
                        identity = OnlyFeeComponentIdentity(
                            OnlyFeeType.BROKER_COMMISSION,
                            OnlyFeeAuthority.BROKER,
                            "source",
                            "schedule",
                            "1",
                            "a" * 64,
                            "rule",
                            "b" * 64,
                            OnlyFeeCalculationScope.FILL,
                            OnlyFeeResolutionPolicy.FILL_EFFECTIVE,
                            direction,
                        )
                        components.append(
                            OnlyFeeApplicationComponent(
                                identity,
                                money(amount),
                                direction,
                                money(amount),
                                money(amount),
                                money(amount),
                                zero,
                                money(amount),
                            )
                        )
                trade_id, timestamp = OnlyTradeId(f"trade-{n}"), OnlyTimestamp(n)
                fee = OnlyFeeApplicationInstruction(
                    f"fee-{n}",
                    subject,
                    trade_id,
                    tuple(components),
                    money(charges),
                    money(rebates),
                    Decimal(rebates) - Decimal(charges),
                    None,
                    "c" * 64,
                    "d" * 64,
                    "e" * 64,
                    OnlyLocalFeeFinality.MODEL_CONFIRMED,
                    f"fee-key-{n}",
                )
                closing = side == "SELL"
                price, quantity = OnlyPrice(Decimal(notional), 2), OnlyQuantity(Decimal(1), 0)
                trade = OnlyPlannedTrade(
                    runtime,
                    OnlyBrokerGatewayId("gateway"),
                    account_id,
                    cluster,
                    order,
                    trade_id,
                    OnlyBrokerUpdateId(f"update-{n}"),
                    instrument,
                    OnlyOrderSide(side),
                    OnlyOrderType.LIMIT,
                    OnlyOffset.CLOSE if closing else OnlyOffset.OPEN,
                    OnlyPositionSide.LONG,
                    OnlyPositionEffect.CLOSE if closing else OnlyPositionEffect.OPEN,
                    OnlyPositionMode.NETTING,
                    OnlySettlementBucket.SETTLED,
                    quantity,
                    price,
                    OnlyMultiplier(Decimal(1), 0),
                    money(notional),
                    money(notional),
                    fee,
                    OnlyOrderFill(trade_id, order, price, quantity, timestamp, timestamp),
                    OnlyLiquiditySide.UNKNOWN,
                    timestamp,
                    timestamp,
                    OnlyTradingDay(date(2026, 10, 19)),
                    n,
                    (n, n, str(trade_id)),
                )
                reduction = None
                if not closing:
                    reduction = OnlyAccountCashReservationTradeReducer().reduce(
                        reservation, trade, terminal_fill=terminal, projection_sequence=9
                    )
                    reservation = reduction.after
                delta = money(-account.position_market_value.amount) if closing else money(notional)
                result = OnlyAccountTradeReducer().reduce(
                    account, reduction, trade, delta, zero, realized_pnl_delta=money(realized), projection_sequence=7
                )
                account = result.after
                observed.append(
                    [
                        str(x.amount)
                        for x in (
                            account.ledger_cash,
                            account.order_reserved_cash,
                            account.fees,
                            account.realized_pnl,
                            account.equity,
                        )
                    ]
                )
                # Direct Manager cannot encode a negative net fee; the formal reducer remains authoritative.
                if case["reference"] == "manager_and_reducer":
                    flow = OnlyAccountTradeCashFlow(
                        runtime,
                        account_id,
                        order,
                        trade_id,
                        OnlyOrderSide(side),
                        money(notional),
                        money(Decimal(charges) - Decimal(rebates)),
                        money(realized),
                        timestamp,
                        n,
                    )
                    direct = native.apply_trade_cash_flow(flow).after
                    assert direct.cash.ledger_cash.amount == account.ledger_cash.amount
                    assert direct.fees.amount == account.fees.amount
                    assert direct.realized_pnl.amount == account.realized_pnl.amount
                else:
                    assert case["reference"] == "reducer_only" and Decimal(rebates) > Decimal(charges)

            assert observed == case["expected"], (case["case"], observed, case["expected"])
            outputs.append({"case": case["case"], "observed": observed})
    return outputs


def compare_native_outputs(observed: list[dict[str, object]]) -> None:
    assert observed == reference_outputs(), "ACCOUNT_NATIVE_PYTHON_MISMATCH"


if __name__ == "__main__":
    print(json.dumps(reference_outputs(), sort_keys=True))
