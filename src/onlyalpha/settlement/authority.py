"""Single-writer Settlement Instruction authority."""

from __future__ import annotations

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
from onlyalpha.settlement.models import (
    OnlySettlementDueTransition,
    OnlySettlementInstruction,
    OnlySettlementInstructionSnapshot,
    OnlySettlementInstructionStatus,
    OnlySettlementTransitionKind,
)


class OnlySettlementAuthority:
    def __init__(self) -> None:
        self._snapshots: dict[OnlySettlementInstructionId, OnlySettlementInstructionSnapshot] = {}

    def register(self, instruction: OnlySettlementInstruction) -> None:
        current = self._snapshots.get(instruction.instruction_id)
        if current is not None:
            if current.instruction != instruction:
                raise ValueError("SETTLEMENT_INSTRUCTION_IDENTITY_CONFLICT")
            return
        day = instruction.trading_day
        flags = (
            instruction.schedule.asset_booked_on <= day,
            instruction.schedule.asset_trade_available_on <= day,
            instruction.schedule.cash_booked_on <= day,
            instruction.schedule.cash_trade_available_on <= day,
            instruction.schedule.cash_withdrawable_on <= day,
            instruction.schedule.legal_settlement_on <= day,
        )
        complete = all((flags[1], flags[3], flags[4], flags[5]))
        status = (
            OnlySettlementInstructionStatus.COMPLETED
            if complete
            else OnlySettlementInstructionStatus.PARTIALLY_EFFECTIVE
            if any(flags)
            else OnlySettlementInstructionStatus.PENDING
        )
        self._snapshots[instruction.instruction_id] = OnlySettlementInstructionSnapshot(
            instruction, *flags, status, 1, int(any(flags)), None
        )

    def require(self, instruction_id: OnlySettlementInstructionId) -> OnlySettlementInstructionSnapshot:
        try:
            return self._snapshots[instruction_id]
        except KeyError as exc:
            raise KeyError(f"unknown Settlement instruction {instruction_id}") from exc

    def due_transitions(self, through: OnlyTradingDay) -> tuple[OnlySettlementDueTransition, ...]:
        due: list[OnlySettlementDueTransition] = []
        for instruction_id, snapshot in self._snapshots.items():
            item = snapshot.instruction.schedule
            candidates = (
                (
                    item.asset_trade_available_on,
                    OnlySettlementTransitionKind.ASSET_TRADE_AVAILABLE,
                    snapshot.asset_trade_available,
                ),
                (
                    item.cash_trade_available_on,
                    OnlySettlementTransitionKind.CASH_TRADE_AVAILABLE,
                    snapshot.cash_trade_available,
                ),
                (item.cash_withdrawable_on, OnlySettlementTransitionKind.CASH_WITHDRAWABLE, snapshot.cash_withdrawable),
                (item.legal_settlement_on, OnlySettlementTransitionKind.LEGAL_SETTLED, snapshot.legal_settled),
            )
            due.extend(
                OnlySettlementDueTransition(instruction_id, effective_on, transition)
                for effective_on, transition, applied in candidates
                if not applied and effective_on <= through
            )
        return tuple(
            sorted(due, key=lambda item: (item.effective_on.value, str(item.instruction_id), item.transition.value))
        )

    def restore_runtime_authority(self, snapshot: OnlySettlementInstructionSnapshot) -> None:
        current = self._snapshots.get(snapshot.instruction.instruction_id)
        if current is not None and current != snapshot:
            raise ValueError("SETTLEMENT_INSTRUCTION_IDENTITY_CONFLICT")
        self._snapshots[snapshot.instruction.instruction_id] = snapshot

    def apply_projection(
        self,
        expected: OnlySettlementInstructionSnapshot | None,
        result: OnlySettlementInstructionSnapshot,
    ) -> None:
        instruction_id = result.instruction.instruction_id
        current = self._snapshots.get(instruction_id)
        if current == result:
            return
        if current != expected:
            raise ValueError("SETTLEMENT_PROJECTION_PRECONDITION_CONFLICT")
        self._snapshots[instruction_id] = result

    def snapshots(self) -> tuple[OnlySettlementInstructionSnapshot, ...]:
        return tuple(self._snapshots[key] for key in sorted(self._snapshots, key=str))

    @property
    def sequence_head(self) -> int:
        return sum(item.version - 1 for item in self._snapshots.values())

    @property
    def records(self) -> tuple[OnlySettlementInstructionSnapshot, ...]:
        return self.snapshots()

    def capture_checkpoint(self) -> object:
        return {"instructions": [item.to_json() for item in self.snapshots()]}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("instructions"), list):
            raise ValueError("Settlement checkpoint authority is invalid")
        restored = {
            item.instruction.instruction_id: item
            for item in (OnlySettlementInstructionSnapshot.from_json(str(value)) for value in payload["instructions"])
        }
        self._snapshots = restored


__all__ = ["OnlySettlementAuthority"]
