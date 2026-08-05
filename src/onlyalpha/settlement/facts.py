"""Settlement maturity durable facts."""

from __future__ import annotations

from dataclasses import dataclass, fields

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
from onlyalpha.settlement.models import OnlySettlementTransitionKind


@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityFactDraft(OnlyDomainModel):
    maturity_identity: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    instruction_id: OnlySettlementInstructionId
    source_order_id: OnlyOrderId
    source_trade_id: OnlyTradeId
    effective_on: OnlyTradingDay
    processed_at: OnlyTimestamp
    transitions: tuple[OnlySettlementTransitionKind, ...]
    asset_available_delta: OnlyQuantity
    cash_trade_available_delta: OnlyMoney
    cash_withdrawable_delta: OnlyMoney
    position_id: OnlyPositionId
    allocation_id: OnlyPositionAllocationId
    instruction_version_before: int
    instruction_version_after: int
    compiled_rule_fingerprint: str
    reference_fingerprint: str

    @property
    def ts_event(self) -> OnlyTimestamp:
        return self.processed_at

    def __post_init__(self) -> None:
        if not self.maturity_identity.startswith("SMAT-") or not self.transitions:
            raise ValueError("Settlement maturity fact requires stable identity and transitions")
        if self.instruction_version_after != self.instruction_version_before + 1:
            raise ValueError("Settlement maturity fact must advance instruction version once")
        if (
            min(
                self.asset_available_delta.value,
                self.cash_trade_available_delta.amount,
                self.cash_withdrawable_delta.amount,
            )
            < 0
        ):
            raise ValueError("Settlement maturity deltas cannot be negative")

    def finalize(self, execution_sequence: int, committed_at: OnlyTimestamp) -> OnlyCommittedSettlementMaturityFact:
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        return OnlyCommittedSettlementMaturityFact(
            **values,
            runtime_sequence=execution_sequence,
            committed_at=committed_at,
        )


@dataclass(frozen=True, slots=True)
class OnlyCommittedSettlementMaturityFact(OnlySettlementMaturityFactDraft):
    runtime_sequence: int
    committed_at: OnlyTimestamp

    @property
    def execution_sequence(self) -> int:
        return self.runtime_sequence

    @property
    def ts_committed(self) -> OnlyTimestamp:
        return self.committed_at

    def __post_init__(self) -> None:
        OnlySettlementMaturityFactDraft.__post_init__(self)
        if self.runtime_sequence < 1 or self.committed_at < self.processed_at:
            raise ValueError("committed Settlement maturity fact sequence/time is invalid")


__all__ = ["OnlyCommittedSettlementMaturityFact", "OnlySettlementMaturityFactDraft"]
