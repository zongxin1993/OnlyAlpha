"""Order lifecycle adapter for buy-side virtual cash Reservations."""

from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice
from onlyalpha.fee.resolver import OnlyFeeResolver
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager


class OnlyOrderStrategyCashReservationAdapter:
    """Bridges Order lifecycle only; trade PnL remains Allocation-authoritative."""

    def __init__(
        self,
        manager: OnlyStrategyLedgerManager,
        base_currency: OnlyCurrency,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        reference_price: Callable[[OnlyOrderSnapshot], OnlyPrice | None],
        fee_resolver: OnlyFeeResolver,
    ) -> None:
        self.__manager = manager
        self.__base_currency = base_currency
        self.__instruments = instruments
        self.__reference_price = reference_price
        self.__fee_resolver = fee_resolver
        self.__keys: dict[OnlyOrderId, OnlyStrategyLedgerKey] = {}
        self.__order_instruments: dict[OnlyOrderId, OnlyInstrumentId] = {}

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        if order.side is not OnlyOrderSide.BUY or order.offset in {
            OnlyOffset.CLOSE,
            OnlyOffset.CLOSE_TODAY,
            OnlyOffset.CLOSE_YESTERDAY,
        }:
            return
        instrument = self.__instruments.get(order.instrument_id)
        if instrument is None:
            raise ValueError("cannot reserve Strategy cash for unknown Instrument")
        if instrument.settlement_currency != self.__base_currency:
            raise ValueError("first-phase Strategy Ledger does not convert currency")
        price = order.price or self.__reference_price(order)
        if price is None:
            raise ValueError("market BUY requires a deterministic reference price")
        amount = price.value * order.quantity.value * instrument.contract_multiplier.value
        quantum = Decimal(1).scaleb(-self.__base_currency.precision)
        notional = OnlyMoney(amount.quantize(quantum, ROUND_HALF_EVEN), self.__base_currency)
        estimated_fee = self.__fee_resolver.estimate_order(order, price, timestamp).reservation_fee
        key = OnlyStrategyLedgerKey(
            order.runtime_id,
            order.account_id,
            order.cluster_id,
            self.__base_currency,
        )
        self.__manager.reserve_cash(key, order.order_id, notional, estimated_fee, timestamp)
        self.__keys[order.order_id] = key
        self.__order_instruments[order.order_id] = order.instrument_id

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        key = self.__keys.get(order_id)
        if key is not None:
            self.__manager.advance_cash_reservation(
                key, order_id, OnlyStrategyCashReservationStage.SENT_TO_BROKER, timestamp
            )

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        key = self.__keys.get(order_id)
        if key is not None:
            self.__manager.advance_cash_reservation(
                key, order_id, OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED, timestamp
            )

    def consume(self, fill: OnlyOrderFill, timestamp: OnlyTimestamp) -> None:
        key = self.__keys.get(fill.order_id)
        if key is None:
            return
        instrument = self.__instruments[self.__order_instruments[fill.order_id]]
        amount = fill.price.value * fill.quantity.value * instrument.contract_multiplier.value
        fee = Decimal(0)
        quantum = Decimal(1).scaleb(-self.__base_currency.precision)
        actual = OnlyMoney((amount + fee).quantize(quantum, ROUND_HALF_EVEN), self.__base_currency)
        self.__manager.consume_cash_reservation(key, fill.order_id, actual, timestamp)

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        key = self.__keys.get(order_id)
        if key is not None:
            self.__manager.release_cash_reservation(key, order_id, timestamp)
