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
        self._sequence = 0

    @property
    def records(self) -> tuple[OnlySettlementRecord, ...]:
        return tuple(self._records)

    @property
    def sequence_head(self) -> int:
        return self._sequence

    def has_instruction(self, instruction_id: str) -> bool:
        return instruction_id in self._pending

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
                self._sequence + 1,
                item.account_id,
                item.source_order_id,
                item.legal_settlement_on,
                "SETTLED" if state.legal_settled else "PENDING",
            )
            self._sequence = record.sequence
            self._records.append(record)
            emitted.append(record)
        return tuple(emitted)

    def restore_execution_authority(
        self,
        instruction: OnlySettlementRuntimeInstruction,
        *,
        asset_released: bool,
        trade_cash_released: bool,
        withdrawable_cash_released: bool,
        legal_settled: bool,
        records: tuple[OnlySettlementRecord, ...],
        sequence_head: int,
    ) -> None:
        if sequence_head < self._sequence or any(item.sequence > sequence_head for item in records):
            raise ValueError("Settlement replay sequence head is invalid")
        self._pending[instruction.instruction_id] = _OnlyPendingSettlement(
            instruction,
            asset_released,
            trade_cash_released,
            withdrawable_cash_released,
            legal_settled,
        )
        known = {item.sequence for item in self._records}
        self._records.extend(item for item in records if item.sequence not in known)
        self._records.sort(key=lambda item: item.sequence)
        self._sequence = sequence_head
