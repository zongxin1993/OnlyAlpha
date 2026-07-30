"""External simulated Broker projections, separate from Runtime truth."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionSide


@dataclass(slots=True)
class _OnlyVirtualPositionState:
    position_side: OnlyPositionSide
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
            instrument_id,
            _OnlyVirtualPositionState(
                OnlyPositionSide.LONG, Decimal(0), Decimal(0), Decimal(0), None, quantity_precision
            ),
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
            instrument_id,
            _OnlyVirtualPositionState(
                OnlyPositionSide.SHORT, Decimal(0), Decimal(0), Decimal(0), None, quantity_precision
            ),
        )
        total_cost = state.average_price.value * state.quantity if state.average_price else Decimal(0)
        total_cost += price.value * quantity
        state.quantity += quantity
        state.settled_quantity += quantity
        quantum = Decimal(1).scaleb(-price.precision)
        state.average_price = OnlyPrice((total_cost / state.quantity).quantize(quantum), price.precision)
        cash_quantum = Decimal(1).scaleb(-self.currency.precision)
        self.cash -= fee.quantize(cash_quantum)

    def apply_short_close(
        self,
        instrument_id: OnlyInstrumentId,
        quantity: Decimal,
        price: OnlyPrice,
        fee: Decimal,
    ) -> None:
        state = self.positions[instrument_id]
        if state.average_price is None or quantity > state.quantity:
            raise ValueError("short close exceeds Broker Position")
        state.frozen_quantity -= quantity
        state.settled_quantity -= quantity
        state.quantity -= quantity
        quantum = Decimal(1).scaleb(-self.currency.precision)
        realized = ((state.average_price.value - price.value) * quantity).quantize(quantum)
        self.cash += realized - fee.quantize(quantum)
        if state.quantity == 0:
            state.average_price = None

    def release_order(self, order: OnlyBrokerOrderSnapshot) -> None:
        remaining = order.remaining_quantity.value
        if order.side is OnlyOrderSide.BUY and order.offset not in {
            OnlyOffset.CLOSE,
            OnlyOffset.CLOSE_TODAY,
            OnlyOffset.CLOSE_YESTERDAY,
        }:
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
                state.position_side,
                OnlyQuantity(state.quantity, state.quantity_precision),
                OnlyQuantity(state.settled_quantity - state.frozen_quantity, state.quantity_precision),
                OnlyQuantity(state.frozen_quantity, state.quantity_precision),
                state.average_price,
                timestamp,
                self.sequence,
            )
            for instrument_id, state in sorted(self.positions.items(), key=lambda item: str(item[0]))
        )

    def capture_checkpoint(self) -> object:
        return {
            "cash": str(self.cash),
            "frozen_cash": str(self.frozen_cash),
            "marks": [
                [instrument_id.to_json(), price.to_json()]
                for instrument_id, price in sorted(self.marks.items(), key=lambda item: str(item[0]))
            ],
            "positions": [
                {
                    "average_price": None if state.average_price is None else state.average_price.to_json(),
                    "frozen_quantity": str(state.frozen_quantity),
                    "instrument_id": instrument_id.to_json(),
                    "position_side": state.position_side.value,
                    "quantity": str(state.quantity),
                    "quantity_precision": state.quantity_precision,
                    "settled_quantity": str(state.settled_quantity),
                }
                for instrument_id, state in sorted(self.positions.items(), key=lambda item: str(item[0]))
            ],
            "sequence": self.sequence,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Virtual Broker Account checkpoint must be an object")
        self.cash = Decimal(str(payload["cash"]))
        self.frozen_cash = Decimal(str(payload["frozen_cash"]))
        self.marks = {
            OnlyInstrumentId.from_json(str(instrument_id)): OnlyPrice.from_json(str(price))
            for instrument_id, price in payload["marks"]
        }
        self.positions = {}
        for item in payload["positions"]:
            if not isinstance(item, dict):
                raise ValueError("Virtual Broker Position checkpoint must be an object")
            average = item["average_price"]
            self.positions[OnlyInstrumentId.from_json(str(item["instrument_id"]))] = _OnlyVirtualPositionState(
                OnlyPositionSide(str(item["position_side"])),
                Decimal(str(item["quantity"])),
                Decimal(str(item["settled_quantity"])),
                Decimal(str(item["frozen_quantity"])),
                None if average is None else OnlyPrice.from_json(str(average)),
                int(item["quantity_precision"]),
            )
        self.sequence = int(payload["sequence"])


class OnlyVirtualBrokerOrderStore:
    def __init__(self) -> None:
        self._orders: dict[OnlyOrderId, OnlyBrokerOrderSnapshot] = {}

    def save(self, order: OnlyBrokerOrderSnapshot) -> None:
        self._orders[order.order_id] = order

    def require(self, order_id: OnlyOrderId) -> OnlyBrokerOrderSnapshot:
        return self._orders[order_id]

    def list(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        return tuple(
            value
            for value in sorted(
                self._orders.values(),
                key=lambda item: (str(item.venue_order_id), str(item.order_id)),
            )
            if value.account_id == account_id
        )

    def open(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        terminal = {OnlyOrderStatus.CANCELLED, OnlyOrderStatus.FILLED, OnlyOrderStatus.REJECTED, OnlyOrderStatus.FAILED}
        return tuple(value for value in self.list(account_id) if value.status not in terminal)

    def capture_checkpoint(self) -> object:
        return [item.to_json() for item in sorted(self._orders.values(), key=lambda item: str(item.order_id))]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Virtual Broker Order checkpoint must be a list")
        self._orders = {
            item.order_id: item for item in (OnlyBrokerOrderSnapshot.from_json(str(raw)) for raw in payload)
        }


class OnlyVirtualBrokerTradeStore:
    def __init__(self) -> None:
        self._trades: dict[OnlyTradeId, OnlyBrokerTradeSnapshot] = {}

    def save(self, trade: OnlyBrokerTradeSnapshot) -> None:
        self._trades.setdefault(trade.trade_id, trade)

    def list(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        return tuple(
            value
            for value in sorted(
                self._trades.values(),
                key=lambda item: (item.source_sequence, str(item.trade_id)),
            )
            if value.account_id == account_id
        )

    def all(self) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        return tuple(sorted(self._trades.values(), key=lambda item: (item.source_sequence, str(item.trade_id))))

    def capture_checkpoint(self) -> object:
        return [item.to_json() for item in sorted(self._trades.values(), key=lambda item: str(item.trade_id))]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Virtual Broker Trade checkpoint must be a list")
        self._trades = {
            item.trade_id: item for item in (OnlyBrokerTradeSnapshot.from_json(str(raw)) for raw in payload)
        }
