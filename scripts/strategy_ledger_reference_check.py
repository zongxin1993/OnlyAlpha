"""Actual Python Ledger/Allocation/valuation against independent literal vectors."""

from __future__ import annotations

# ruff: noqa: E402
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.models import OnlyPositionTrade
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyFeeEntry,
    OnlyStrategyMarkPrice,
    OnlyStrategyTradeAccountingInput,
)
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService


def reference_outputs() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    currency = OnlyCurrency("USD", 2)
    runtime, account = OnlyRuntimeId("r"), OnlyAccountId("a")
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    now = OnlyTimestamp(0)

    def money(value: str | Decimal) -> OnlyMoney:
        return OnlyMoney(Decimal(value), currency)

    with localcontext() as context:
        context.prec = 128
        for line in (ROOT / "test-data/strategy-ledger/valuation-v1.jsonl").read_text().splitlines():
            case = json.loads(line)
            manager = OnlyStrategyLedgerManager(runtime)
            allocations = OnlyPositionAllocationManager(runtime)
            for c in ("c1", "c2"):
                key = OnlyStrategyLedgerKey(runtime, account, OnlyClusterId(c), currency)
                manager.create_ledger(key, money("1000"), now)
                manager.activate_ledger(key, now)
            for seq, item in enumerate(case["trades"], 1):
                cluster = OnlyClusterId(item["cluster"])
                key = OnlyStrategyLedgerKey(runtime, account, cluster, currency)
                order = OnlyOrderId(f"order-{seq}")
                trade = OnlyPositionTrade(
                    OnlyTradeId(f"trade-{seq}"),
                    OnlyVenueTradeId(f"venue-{seq}"),
                    order,
                    cluster,
                    runtime,
                    account,
                    instrument,
                    OnlyOrderSide.BUY,
                    OnlyDirection.BUY,
                    OnlyOffset.OPEN,
                    OnlyPositionSide.LONG,
                    OnlyPrice(Decimal(item["price"]), 8),
                    OnlyQuantity(Decimal(item["quantity"]), 8),
                    money(item["fee"]),
                    now,
                    now,
                    seq,
                    settlement_bucket=OnlySettlementBucket.SETTLED,
                    multiplier=OnlyMultiplier(Decimal(1), 0),
                )
                manager.reserve_cash(key, order, money(item["cost"]), money(item["fee"]), now)
                reservation = manager.require_snapshot(key).reservations[-1]
                allocations.apply_trade(trade)
                owned = allocations.list_by_cluster(cluster)
                after = owned[0]
                fee = OnlyStrategyFeeEntry(
                    OnlyStrategyFeeEntryId(f"fee-{seq}"),
                    key,
                    money(item["fee"]),
                    OnlyStrategyFeeType.COMMISSION,
                    trade.trade_id,
                    order,
                    now,
                    now,
                    seq,
                )
                accounting = OnlyStrategyTradeAccountingInput(
                    trade, None, None, after, money("0"), money(item["cost"]), (fee,), reservation, now, seq
                )
                manager.apply_trade_accounting(key, accounting)
                valuation = OnlyStrategyValuationService().value(
                    key,
                    owned,
                    (OnlyStrategyMarkPrice(instrument, OnlyPrice(Decimal(item["mark"]), 8), 1, "recorded"),),
                    {instrument: OnlyMultiplier(Decimal(1), 0)},
                    now,
                    now,
                    1,
                )
                manager.apply_valuation(valuation)
                s = manager.require_snapshot(key)
                actual = {
                    "cash": str(s.cash.ledger_cash.amount),
                    "position_cost": str(valuation.position_cost.amount),
                    "market_value": str(valuation.position_market_value.amount),
                    "unrealized_pnl": str(valuation.unrealized_pnl.amount),
                    "fees": str(s.pnl.fees.amount),
                    "equity": str(s.equity.equity.amount),
                }
                if actual != item["expected"]:
                    raise ValueError(f"STRATEGY_LEDGER_PYTHON_LITERAL_CONFLICT:{case['case']}:{actual}")
                result.append({"case": case["case"], "cluster": item["cluster"], **actual})
    return result


def compare_native_outputs(native: list[dict[str, object]]) -> None:
    if native != reference_outputs():
        raise ValueError("STRATEGY_LEDGER_PYTHON_RUST_CONFLICT")
