from decimal import Decimal

from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position import (
    OnlyPositionAllocationManager,
    OnlyPositionSide,
    OnlyPositionTrade,
    OnlySettlementBucket,
)
from onlyalpha.strategy_ledger.enums import OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyFeeEntry, OnlyStrategyTradeAccountingInput

RUNTIME = OnlyRuntimeId("strategy-ledger-demo")
ACCOUNT = OnlyAccountId("demo-account")
A = OnlyClusterId("cluster-a")
B = OnlyClusterId("cluster-b")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("510300"), OnlyVenueId("XSHG"))
CNY = OnlyCurrency("CNY", 2)


def create(cluster: OnlyClusterId = A) -> tuple[OnlyStrategyLedgerManager, OnlyStrategyLedgerKey]:
    manager = OnlyStrategyLedgerManager(RUNTIME)
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, cluster, CNY)
    manager.create_ledger(key, OnlyMoney(Decimal("100000.00"), CNY), OnlyTimestamp(0))
    manager.activate_ledger(key, OnlyTimestamp(0))
    return manager, key


def trade(
    sequence: int, side: OnlyOrderSide, quantity: str, price: str, fee: str = "0.00", *, cluster: OnlyClusterId = A
) -> OnlyPositionTrade:
    timestamp = OnlyTimestamp(sequence * 1_000)
    return OnlyPositionTrade(
        OnlyTradeId(f"demo-trade-{cluster}-{sequence}"),
        None,
        OnlyOrderId(f"demo-order-{cluster}-{sequence}"),
        cluster,
        RUNTIME,
        ACCOUNT,
        INSTRUMENT,
        side,
        OnlyDirection.BUY if side is OnlyOrderSide.BUY else OnlyDirection.SELL,
        OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
        OnlyPositionSide.LONG,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyMoney(Decimal(fee), CNY),
        timestamp,
        timestamp,
        sequence,
        settlement_bucket=OnlySettlementBucket.SETTLED,
    )


def apply(
    manager: OnlyStrategyLedgerManager,
    key: OnlyStrategyLedgerKey,
    allocations: OnlyPositionAllocationManager,
    item: OnlyPositionTrade,
) -> OnlyStrategyTradeAccountingInput:
    before_values = allocations.list_by_cluster(key.cluster_id)
    before = before_values[0] if before_values else None
    reservation = None
    if item.side is OnlyOrderSide.BUY:
        manager.reserve_cash(
            key,
            item.order_id,
            OnlyMoney(item.price.value * item.quantity.value, CNY),
            item.fee,
            item.ts_event,
        )
        reservation = manager.require_snapshot(key).reservations[-1]
    allocations.apply_trade(item)
    after_values = allocations.list_by_cluster(key.cluster_id)
    after = after_values[0] if after_values else None
    realized_before = Decimal(0) if before is None else before.realized_pnl.amount
    realized_after = Decimal(0) if after is None else after.realized_pnl.amount

    def cost(value: object) -> Decimal:
        if value is None or value.average_open_price is None:  # type: ignore[union-attr]
            return Decimal(0)
        return value.average_open_price.value * value.total_quantity.value  # type: ignore[union-attr]

    fee = OnlyStrategyFeeEntry(
        OnlyStrategyFeeEntryId(f"demo-fee-{item.trade_id}"),
        key,
        item.fee,
        OnlyStrategyFeeType.COMMISSION,
        item.trade_id,
        item.order_id,
        item.ts_event,
        item.ts_init,
        sequence=item.external_sequence or 0,
    )
    accounting = OnlyStrategyTradeAccountingInput(
        item,
        None,
        before,
        after,
        OnlyMoney(realized_after - realized_before, CNY),
        OnlyMoney(cost(after) - cost(before), CNY),
        (fee,),
        reservation,
        item.ts_event,
        item.external_sequence or 0,
    )
    manager.apply_trade_accounting(key, accounting)
    return accounting
