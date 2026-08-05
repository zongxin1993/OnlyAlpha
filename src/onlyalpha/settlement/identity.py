"""Stable identities for settlement instructions and maturity operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
from onlyalpha.settlement.models import OnlySettlementInstruction, OnlySettlementTransitionKind


def only_settlement_instruction_id(payload: dict[str, object]) -> OnlySettlementInstructionId:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return OnlySettlementInstructionId(f"SINS-{hashlib.sha256(encoded).hexdigest()}")


@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityIdentity(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    instruction_id: OnlySettlementInstructionId
    effective_on: OnlyTradingDay
    transitions: tuple[OnlySettlementTransitionKind, ...]

    def __post_init__(self) -> None:
        canonical = tuple(sorted(set(self.transitions), key=lambda item: item.value))
        if not canonical or canonical != self.transitions:
            raise ValueError("Settlement maturity transitions must be non-empty, unique, and sorted")

    def value(self, instruction_before_fingerprint: str) -> str:
        authority = "\x1f".join(
            (
                str(self.runtime_id),
                str(self.instruction_id),
                self.effective_on.value.isoformat(),
                ",".join(item.value for item in self.transitions),
                instruction_before_fingerprint,
            )
        )
        return f"SMAT-{hashlib.sha256(authority.encode('utf-8')).hexdigest()}"


def only_instruction_identity_payload(instruction: OnlySettlementInstruction) -> dict[str, object]:
    return {
        "runtime_id": str(instruction.runtime_id),
        "account_id": str(instruction.account_id),
        "order_id": str(instruction.order_id),
        "trade_id": str(instruction.trade_id),
        "position_id": str(instruction.position_id),
        "allocation_id": str(instruction.allocation_id),
        "quantity": instruction.trade_quantity.to_dict(),
        "schedule": instruction.schedule.to_dict(),
        "compiled_rule_fingerprint": instruction.compiled_rule_fingerprint,
    }


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
