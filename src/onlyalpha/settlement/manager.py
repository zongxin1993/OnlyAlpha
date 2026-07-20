"""Instruction-driven Runtime settlement lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.runtime_rules import OnlySettlementRuntimeInstruction


@dataclass(frozen=True, slots=True)
class OnlySettlementRecord:
    instruction_id: str
    instrument_id: str
    source_trade_id: str
    asset_quantity: Decimal
    cash_amount: Decimal
    booked_quantity: Decimal
    available_quantity: Decimal
    trade_available_cash: Decimal
    withdrawable_cash: Decimal
    legal_settled: bool
    processed_on: OnlyTradingDay
    sequence: int = 0
    account_id: str = ""
    source_order_id: str = ""
    legal_settlement_date: OnlyTradingDay | None = None
    status: str = "BOOKED"


@dataclass(slots=True)
class _OnlyPendingSettlement:
    instruction: OnlySettlementRuntimeInstruction
    asset_released: bool = False
    trade_cash_released: bool = False
    withdrawable_cash_released: bool = False
    legal_settled: bool = False


class OnlySettlementManager:
    """Own settlement state; it never decides settlement dates."""

    def __init__(self) -> None:
        self._pending: dict[str, _OnlyPendingSettlement] = {}
        self._records: list[OnlySettlementRecord] = []

    @property
    def records(self) -> tuple[OnlySettlementRecord, ...]:
        return tuple(self._records)

    def register(self, instruction: OnlySettlementRuntimeInstruction) -> None:
        current = self._pending.get(instruction.instruction_id)
        if current is not None:
            if current.instruction != instruction:
                raise ValueError("settlement instruction id conflicts with existing instruction")
            return
        self._pending[instruction.instruction_id] = _OnlyPendingSettlement(instruction)

    def advance(self, trading_day: OnlyTradingDay) -> tuple[OnlySettlementRecord, ...]:
        emitted: list[OnlySettlementRecord] = []
        for key in sorted(self._pending):
            state = self._pending[key]
            item = state.instruction
            before = (
                state.asset_released,
                state.trade_cash_released,
                state.withdrawable_cash_released,
                state.legal_settled,
            )
            state.asset_released |= trading_day >= item.asset_available_on
            state.trade_cash_released |= trading_day >= item.cash_trade_available_on
            state.withdrawable_cash_released |= trading_day >= item.cash_withdrawable_on
            state.legal_settled |= trading_day >= item.legal_settlement_on
            after = (
                state.asset_released,
                state.trade_cash_released,
                state.withdrawable_cash_released,
                state.legal_settled,
            )
            if before == after:
                continue
            record = OnlySettlementRecord(
                item.instruction_id,
                item.instrument_id,
                item.source_trade_id,
                item.asset_quantity,
                item.cash_amount,
                item.asset_quantity,
                item.asset_quantity if state.asset_released else Decimal(0),
                item.cash_amount if state.trade_cash_released else Decimal(0),
                item.cash_amount if state.withdrawable_cash_released else Decimal(0),
                state.legal_settled,
                trading_day,
                len(self._records) + 1,
                item.account_id,
                item.source_order_id,
                item.legal_settlement_on,
                "SETTLED" if state.legal_settled else "PENDING",
            )
            self._records.append(record)
            emitted.append(record)
        return tuple(emitted)
