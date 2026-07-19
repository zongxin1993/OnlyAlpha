"""Virtual external truth stores, physically separate from Runtime Managers."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


@dataclass(slots=True)
class _OnlyVirtualPositionState:
    quantity: Decimal
    settled_quantity: Decimal
    frozen_quantity: Decimal
    average_price: OnlyPrice | None
    quantity_precision: int


class OnlyVirtualBrokerAccountStore:
    def __init__(
        self,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        currency: OnlyCurrency,
        initial_cash: OnlyMoney,
    ) -> None:
        self.gateway_id = gateway_id
        self.account_id = account_id
        self.currency = currency
        self.cash = initial_cash.amount
        self.frozen_cash = Decimal(0)
        self.positions: dict[OnlyInstrumentId, _OnlyVirtualPositionState] = {}
        self.marks: dict[OnlyInstrumentId, OnlyPrice] = {}
        self.sequence = 0

    def reserve_buy(self, amount: Decimal) -> bool:
        amount = amount.quantize(Decimal(1).scaleb(-self.currency.precision))
        if amount > self.cash - self.frozen_cash:
            return False
        self.frozen_cash += amount
        return True

    def reserve_sell(self, instrument_id: OnlyInstrumentId, quantity: Decimal) -> bool:
        position = self.positions.get(instrument_id)
        if position is None or quantity > position.settled_quantity - position.frozen_quantity:
            return False
        position.frozen_quantity += quantity
        return True

    def apply_buy(
        self,
        instrument_id: OnlyInstrumentId,
        quantity: Decimal,
        price: OnlyPrice,
        reserved: Decimal,
        fee: Decimal,
        quantity_precision: int,
        *,
        asset_available: bool = False,
    ) -> None:
        quantum = Decimal(1).scaleb(-self.currency.precision)
        cost = (price.value * quantity).quantize(quantum)
        reserved = reserved.quantize(quantum)
        fee = fee.quantize(quantum)
        self.frozen_cash -= reserved
        self.cash -= cost + fee
        state = self.positions.setdefault(
            instrument_id, _OnlyVirtualPositionState(Decimal(0), Decimal(0), Decimal(0), None, quantity_precision)
        )
        total_cost = (state.average_price.value * state.quantity if state.average_price else Decimal(0)) + cost
        state.quantity += quantity
        # Broker Store is an external snapshot, not the legal settlement
        # engine. Runtime availability is governed by SettlementInstruction.
        if asset_available:
            state.settled_quantity += quantity
        price_quantum = Decimal(1).scaleb(-price.precision)
        state.average_price = OnlyPrice((total_cost / state.quantity).quantize(price_quantum), price.precision)

    def apply_sell(
        self,
        instrument_id: OnlyInstrumentId,
        quantity: Decimal,
        price: OnlyPrice,
        fee: Decimal,
    ) -> None:
        state = self.positions[instrument_id]
        state.frozen_quantity -= quantity
        state.settled_quantity -= quantity
        state.quantity -= quantity
        quantum = Decimal(1).scaleb(-self.currency.precision)
        self.cash += (price.value * quantity).quantize(quantum) - fee.quantize(quantum)
        if state.quantity == 0:
            state.average_price = None

    def apply_short_open(
        self,
        instrument_id: OnlyInstrumentId,
        quantity: Decimal,
        price: OnlyPrice,
        fee: Decimal,
        quantity_precision: int,
    ) -> None:
        state = self.positions.setdefault(
            instrument_id, _OnlyVirtualPositionState(Decimal(0), Decimal(0), Decimal(0), None, quantity_precision)
        )
        total_cost = state.average_price.value * state.quantity if state.average_price else Decimal(0)
        total_cost += price.value * quantity
        state.quantity += quantity
        state.settled_quantity += quantity
        quantum = Decimal(1).scaleb(-price.precision)
        state.average_price = OnlyPrice((total_cost / state.quantity).quantize(quantum), price.precision)
        cash_quantum = Decimal(1).scaleb(-self.currency.precision)
        self.cash -= fee.quantize(cash_quantum)

    def release_order(self, order: OnlyBrokerOrderSnapshot) -> None:
        remaining = order.remaining_quantity.value
        if order.side is OnlyOrderSide.BUY:
            assert order.price is not None
            self.frozen_cash -= order.price.value * remaining
        else:
            state = self.positions.get(order.instrument_id)
            if state is not None:
                state.frozen_quantity -= remaining

    def settle(self) -> None:
        for state in self.positions.values():
            state.settled_quantity = state.quantity

    def mark(self, instrument_id: OnlyInstrumentId, price: OnlyPrice) -> None:
        self.marks[instrument_id] = price

    def account_snapshot(self, timestamp: OnlyTimestamp) -> OnlyBrokerAccountSnapshot:
        self.sequence += 1
        position_value = sum(
            state.quantity
            * (
                self.marks[instrument_id].value
                if instrument_id in self.marks
                else state.average_price.value
                if state.average_price is not None
                else Decimal(0)
            )
            for instrument_id, state in self.positions.items()
        )
        quantum = Decimal(1).scaleb(-self.currency.precision)
        return OnlyBrokerAccountSnapshot(
            self.gateway_id,
            self.account_id,
            OnlyMoney(self.cash, self.currency),
            OnlyMoney(self.cash - self.frozen_cash, self.currency),
            OnlyMoney(self.frozen_cash, self.currency),
            OnlyMoney((self.cash + position_value).quantize(quantum), self.currency),
            timestamp,
            self.sequence,
        )

    def position_snapshots(self, timestamp: OnlyTimestamp) -> tuple[OnlyBrokerPositionSnapshot, ...]:
        self.sequence += 1
        return tuple(
            OnlyBrokerPositionSnapshot(
                self.gateway_id,
                self.account_id,
                instrument_id,
                OnlyQuantity(state.quantity, state.quantity_precision),
                OnlyQuantity(state.settled_quantity - state.frozen_quantity, state.quantity_precision),
                OnlyQuantity(state.frozen_quantity, state.quantity_precision),
                state.average_price,
                timestamp,
                self.sequence,
            )
            for instrument_id, state in sorted(self.positions.items(), key=lambda item: str(item[0]))
        )


class OnlyVirtualBrokerOrderStore:
    def __init__(self) -> None:
        self._orders: dict[OnlyOrderId, OnlyBrokerOrderSnapshot] = {}

    def save(self, order: OnlyBrokerOrderSnapshot) -> None:
        self._orders[order.order_id] = order

    def require(self, order_id: OnlyOrderId) -> OnlyBrokerOrderSnapshot:
        return self._orders[order_id]

    def list(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        return tuple(value for value in self._orders.values() if value.account_id == account_id)

    def open(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        terminal = {OnlyOrderStatus.CANCELLED, OnlyOrderStatus.FILLED, OnlyOrderStatus.REJECTED, OnlyOrderStatus.FAILED}
        return tuple(value for value in self.list(account_id) if value.status not in terminal)


class OnlyVirtualBrokerTradeStore:
    def __init__(self) -> None:
        self._trades: dict[OnlyTradeId, OnlyBrokerTradeSnapshot] = {}

    def save(self, trade: OnlyBrokerTradeSnapshot) -> None:
        self._trades.setdefault(trade.trade_id, trade)

    def list(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        return tuple(value for value in self._trades.values() if value.account_id == account_id)
