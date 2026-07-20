"""Instruction-driven fee fact manager."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.market.runtime_rules import OnlyFeeInstruction


@dataclass(frozen=True, slots=True)
class OnlyFeeRecord:
    fee_record_id: str
    account_id: str
    instrument_id: str
    order_id: str
    trade_id: str
    fee_type: str
    accrued: Decimal
    charged: Decimal
    currency: str
    sequence: int


class OnlyFeeManager:
    """Owns applied fee facts; fee calculation remains in Market Rules."""

    def __init__(self) -> None:
        self._records: list[OnlyFeeRecord] = []
        self._trade_ids: set[str] = set()

    @property
    def records(self) -> tuple[OnlyFeeRecord, ...]:
        return tuple(self._records)

    def apply(
        self, instruction: OnlyFeeInstruction, *, account_id: str, instrument_id: str
    ) -> tuple[OnlyFeeRecord, ...]:
        if instruction.source_trade_id in self._trade_ids:
            return ()
        emitted: list[OnlyFeeRecord] = []
        breakdown = instruction.breakdown
        components = {
            "commission": breakdown.commission,
            "exchange_fee": breakdown.exchange_fee,
            "clearing_fee": breakdown.clearing_fee,
            "regulatory_fee": breakdown.regulatory_fee,
            "tax": breakdown.tax,
            "transfer_fee": breakdown.transfer_fee,
            "borrow_fee": breakdown.borrow_fee,
            "funding_fee": breakdown.funding_fee,
            "other_fee": breakdown.other_fee,
            **dict(breakdown.components),
        }
        for fee_type, amount in sorted(components.items()):
            if amount == 0:
                continue
            sequence = len(self._records) + 1
            record = OnlyFeeRecord(
                f"FEE-{instruction.source_trade_id}-{fee_type}-{sequence:08d}",
                account_id,
                instrument_id,
                instruction.source_order_id,
                instruction.source_trade_id,
                fee_type,
                amount,
                amount,
                breakdown.currency,
                sequence,
            )
            self._records.append(record)
            emitted.append(record)
        self._trade_ids.add(instruction.source_trade_id)
        return tuple(emitted)
