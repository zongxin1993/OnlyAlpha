"""Instruction-driven Runtime settlement lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency
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


@dataclass(frozen=True, slots=True)
class OnlySettlementExecutionAuthoritySnapshot:
    """Manager-owned Settlement authority for one instruction."""

    instruction: OnlySettlementRuntimeInstruction
    cash_currency: OnlyCurrency | None
    asset_released: bool
    trade_cash_released: bool
    withdrawable_cash_released: bool
    legal_settled: bool
    version: int
    records: tuple[OnlySettlementRecord, ...]
    record_sequence_head: int


@dataclass(slots=True)
class _OnlyPendingSettlement:
    instruction: OnlySettlementRuntimeInstruction
    cash_currency: OnlyCurrency | None = None
    asset_released: bool = False
    trade_cash_released: bool = False
    withdrawable_cash_released: bool = False
    legal_settled: bool = False
    version: int = 1


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

    def get_execution_authority(self, instruction_id: str) -> OnlySettlementExecutionAuthoritySnapshot | None:
        pending = self._pending.get(instruction_id)
        if pending is None:
            return None
        return OnlySettlementExecutionAuthoritySnapshot(
            pending.instruction,
            pending.cash_currency,
            pending.asset_released,
            pending.trade_cash_released,
            pending.withdrawable_cash_released,
            pending.legal_settled,
            pending.version,
            tuple(item for item in self._records if item.instruction_id == instruction_id),
            self._sequence,
        )

    def register(
        self,
        instruction: OnlySettlementRuntimeInstruction,
        *,
        cash_currency: OnlyCurrency | None = None,
    ) -> None:
        current = self._pending.get(instruction.instruction_id)
        if current is not None:
            if current.instruction != instruction or (
                cash_currency is not None and current.cash_currency not in {None, cash_currency}
            ):
                raise ValueError("settlement instruction id conflicts with existing instruction")
            if current.cash_currency is None:
                current.cash_currency = cash_currency
            return
        self._pending[instruction.instruction_id] = _OnlyPendingSettlement(instruction, cash_currency)

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
            state.version += 1
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
        version: int,
        cash_currency: OnlyCurrency,
    ) -> None:
        if version < 1 or sequence_head < self._sequence or any(item.sequence > sequence_head for item in records):
            raise ValueError("Settlement replay sequence head is invalid")
        current = self._pending.get(instruction.instruction_id)
        if current is not None and current.instruction != instruction:
            raise ValueError("settlement instruction id conflicts with existing instruction")
        expected = {item.sequence: item for item in records}
        if len(expected) != len(records):
            raise ValueError("Settlement replay record sequences are duplicated")
        existing = {item.sequence: item for item in self._records}
        for sequence, item in expected.items():
            if (known := existing.get(sequence)) is not None and known != item:
                raise ValueError("Settlement replay record sequence conflicts with existing authority")
        pending = dict(self._pending)
        pending[instruction.instruction_id] = _OnlyPendingSettlement(
            instruction,
            cash_currency,
            asset_released,
            trade_cash_released,
            withdrawable_cash_released,
            legal_settled,
            version,
        )
        installed_records = list(self._records)
        installed_records.extend(item for item in records if item.sequence not in existing)
        installed_records.sort(key=lambda item: item.sequence)
        self._pending = pending
        self._records = installed_records
        self._sequence = sequence_head

    def capture_checkpoint(self) -> object:
        return {
            "pending": [
                {
                    "asset_released": state.asset_released,
                    "cash_currency": None if state.cash_currency is None else state.cash_currency.code,
                    "instruction": self._instruction_payload(state.instruction),
                    "legal_settled": state.legal_settled,
                    "trade_cash_released": state.trade_cash_released,
                    "version": state.version,
                    "withdrawable_cash_released": state.withdrawable_cash_released,
                }
                for _, state in sorted(self._pending.items())
            ],
            "records": [self._record_payload(item) for item in self._records],
            "sequence": self._sequence,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Settlement checkpoint must be an object")
        records = tuple(self._record_from_payload(item) for item in payload["records"])
        sequence = int(payload["sequence"])
        for item in payload["pending"]:
            if not isinstance(item, dict) or item["cash_currency"] is None:
                raise ValueError("Settlement checkpoint authority is incomplete")
            instruction = self._instruction_from_payload(item["instruction"])
            self.restore_execution_authority(
                instruction,
                asset_released=bool(item["asset_released"]),
                trade_cash_released=bool(item["trade_cash_released"]),
                withdrawable_cash_released=bool(item["withdrawable_cash_released"]),
                legal_settled=bool(item["legal_settled"]),
                records=tuple(record for record in records if record.instruction_id == instruction.instruction_id),
                sequence_head=sequence,
                version=int(item["version"]),
                cash_currency=OnlyCurrency(str(item["cash_currency"])),
            )

    @staticmethod
    def _instruction_payload(item: OnlySettlementRuntimeInstruction) -> dict[str, object]:
        return {
            "account_id": item.account_id,
            "asset_available_on": item.asset_available_on.value.isoformat(),
            "asset_quantity": str(item.asset_quantity),
            "cash_amount": str(item.cash_amount),
            "cash_trade_available_on": item.cash_trade_available_on.value.isoformat(),
            "cash_withdrawable_on": item.cash_withdrawable_on.value.isoformat(),
            "instruction_id": item.instruction_id,
            "instrument_id": item.instrument_id,
            "legal_settlement_on": item.legal_settlement_on.value.isoformat(),
            "source_order_id": item.source_order_id,
            "source_trade_id": item.source_trade_id,
        }

    @staticmethod
    def _instruction_from_payload(payload: object) -> OnlySettlementRuntimeInstruction:
        if not isinstance(payload, dict):
            raise ValueError("Settlement instruction checkpoint must be an object")
        return OnlySettlementRuntimeInstruction(
            str(payload["instruction_id"]),
            str(payload["instrument_id"]),
            str(payload["source_trade_id"]),
            Decimal(str(payload["asset_quantity"])),
            Decimal(str(payload["cash_amount"])),
            OnlyTradingDay(date.fromisoformat(str(payload["asset_available_on"]))),
            OnlyTradingDay(date.fromisoformat(str(payload["cash_trade_available_on"]))),
            OnlyTradingDay(date.fromisoformat(str(payload["cash_withdrawable_on"]))),
            OnlyTradingDay(date.fromisoformat(str(payload["legal_settlement_on"]))),
            str(payload["account_id"]),
            str(payload["source_order_id"]),
        )

    @staticmethod
    def _record_payload(item: OnlySettlementRecord) -> dict[str, object]:
        return {
            "account_id": item.account_id,
            "asset_quantity": str(item.asset_quantity),
            "available_quantity": str(item.available_quantity),
            "booked_quantity": str(item.booked_quantity),
            "cash_amount": str(item.cash_amount),
            "instruction_id": item.instruction_id,
            "instrument_id": item.instrument_id,
            "legal_settled": item.legal_settled,
            "legal_settlement_date": None
            if item.legal_settlement_date is None
            else item.legal_settlement_date.value.isoformat(),
            "processed_on": item.processed_on.value.isoformat(),
            "sequence": item.sequence,
            "source_order_id": item.source_order_id,
            "source_trade_id": item.source_trade_id,
            "status": item.status,
            "trade_available_cash": str(item.trade_available_cash),
            "withdrawable_cash": str(item.withdrawable_cash),
        }

    @staticmethod
    def _record_from_payload(payload: object) -> OnlySettlementRecord:
        if not isinstance(payload, dict):
            raise ValueError("Settlement record checkpoint must be an object")

        def day(value: object) -> OnlyTradingDay:
            return OnlyTradingDay(date.fromisoformat(str(value)))

        legal = payload["legal_settlement_date"]
        return OnlySettlementRecord(
            str(payload["instruction_id"]),
            str(payload["instrument_id"]),
            str(payload["source_trade_id"]),
            Decimal(str(payload["asset_quantity"])),
            Decimal(str(payload["cash_amount"])),
            Decimal(str(payload["booked_quantity"])),
            Decimal(str(payload["available_quantity"])),
            Decimal(str(payload["trade_available_cash"])),
            Decimal(str(payload["withdrawable_cash"])),
            bool(payload["legal_settled"]),
            day(payload["processed_on"]),
            int(payload["sequence"]),
            str(payload["account_id"]),
            str(payload["source_order_id"]),
            None if legal is None else day(legal),
            str(payload["status"]),
        )


__all__ = [
    "OnlySettlementExecutionAuthoritySnapshot",
    "OnlySettlementManager",
    "OnlySettlementRecord",
]
